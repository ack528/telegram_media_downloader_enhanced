"""Measure Telegram download throughput under different strategies.

Stop the downloader first: running two clients with the same login at once
can get the session revoked.  The session file is copied to a temporary
directory, and downloaded bytes are discarded.

    python scripts/speed_benchmark.py --base C:\\path\\to\\tdl --chat ixsnv
    python scripts/speed_benchmark.py --base ... --chat ixsnv --plan nodes

Plans:
  params  compare Pyrogram's downloader with parallel connection/thread counts
  cap     the shipped defaults against the in-flight cap that avoids stalls
  nodes   compare Clash nodes for the group that carries Telegram traffic
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyrogram  # noqa: E402
from pyrogram.file_id import FileId  # noqa: E402
from ruamel.yaml import YAML  # noqa: E402

from module.fast_download import PART_SIZE, close_pool, get_pool, iter_file_parallel  # noqa: E402

FLOOD_EVENTS = []


class FloodCounter(logging.Handler):
    """Count FloodWait / FloodPremiumWait sleeps reported by Pyrogram."""

    def emit(self, record):
        message = record.getMessage()
        if "Waiting for" in message:
            FLOOD_EVENTS.append(message)


UNCAPPED = 64

PARAM_PLAN = [
    # name, mode, connections, threads, files[, max in flight per DC]
    ("pyrogram x1", "pyrogram", 1, 1, 1),
    ("pyrogram x5 (current)", "pyrogram", 1, 1, 5),
    ("c1 t2 x1", "fast", 1, 2, 1),
    ("c1 t4 x1", "fast", 1, 4, 1),
    ("c1 t8 x1", "fast", 1, 8, 1),
    ("c2 t4 x1", "fast", 2, 4, 1),
    ("c1 t2 x5", "fast", 1, 2, 5),
    ("c1 t4 x5", "fast", 1, 4, 5),
    ("c2 t2 x5", "fast", 2, 2, 5),
    ("c2 t4 x5", "fast", 2, 4, 5),
    ("c4 t2 x5", "fast", 4, 2, 5),
]

CAP_PLAN = [
    ("pyrogram x5 (old)", "pyrogram", 1, 1, 5),
    ("c2 t4 x5 cap8 (default)", "fast", 2, 4, 5, 8),
    ("c1 t4 x5 uncapped", "fast", 1, 4, 5),
    ("c1 t4 x5 cap8", "fast", 1, 4, 5, 8),
    ("c2 t4 x5 cap12", "fast", 2, 4, 5, 12),
    ("c2 t4 x1 cap8", "fast", 2, 4, 1, 8),
]

# Clash node name hints per region, nearest to each Telegram DC first.
REGION_HINTS = {
    "NL": ("荷兰", "netherlands", "amsterdam", "🇳🇱", " nl"),
    "DE": ("德国", "germany", "frankfurt", "🇩🇪", " de"),
    "GB": ("英国", "united kingdom", "london", "🇬🇧", " uk"),
    "FR": ("法国", "france", "paris", "🇫🇷"),
    "SG": ("新加坡", "singapore", "🇸🇬", " sg"),
    "JP": ("日本", "japan", "tokyo", "🇯🇵", " jp"),
    "HK": ("香港", "hong kong", "🇭🇰", " hk"),
    "US": ("美国", "united states", "🇺🇸", " us"),
}


async def find_videos(client, chat, scan, min_size, count):
    videos = []
    async for message in client.get_chat_history(chat, limit=scan):
        media = message.video or message.document
        if media and (media.file_size or 0) >= min_size:
            videos.append(message)
            if len(videos) >= count:
                break
    return videos


async def pull(client, message, mode, connections, threads, cap, offset, counter):
    """Stream from ``offset`` until cancelled, adding bytes to ``counter``."""
    media = message.video or message.document
    file_id = FileId.decode(media.file_id)
    if mode == "pyrogram":
        stream = client.get_file(file_id, media.file_size, 0, offset)
    else:
        stream = iter_file_parallel(
            client,
            file_id,
            media.file_size,
            offset,
            connections=connections,
            threads=threads,
            max_in_flight=cap,
        )
    try:
        async for chunk in stream:
            counter[0] += len(chunk)
    finally:
        await stream.aclose()


async def run_case(client, videos, case, seconds, run_index):
    """Time-boxed: bytes received in ``seconds`` (stalls show up as 0)."""
    name, mode, connections, threads, files = case[:5]
    cap = case[5] if len(case) > 5 else UNCAPPED
    FLOOD_EVENTS.clear()
    targets = videos[:files]
    if mode == "fast":
        # Open the pool before timing so connection setup is not measured.
        dc_ids = {FileId.decode((m.video or m.document).file_id).dc_id for m in targets}
        for dc_id in dc_ids:
            await get_pool(client).sessions(dc_id, connections)
    counter = [0]
    jobs = []
    for i, message in enumerate(targets):
        size_parts = (message.video or message.document).file_size // PART_SIZE
        offset = ((run_index * 7 + i * 3) * 40) % max(size_parts - 200, 1)
        jobs.append(
            asyncio.ensure_future(
                pull(client, message, mode, connections, threads, cap, offset, counter)
            )
        )
    start = time.perf_counter()
    await asyncio.sleep(seconds)
    for job in jobs:
        job.cancel()
    await asyncio.gather(*jobs, return_exceptions=True)
    received = counter[0]
    elapsed = time.perf_counter() - start
    speed = received / elapsed / 1024 / 1024
    result = {
        "case": name,
        "files": files,
        "mb": round(received / 1024 / 1024, 1),
        "seconds": round(elapsed, 1),
        "mb_per_s": round(speed, 2),
        "per_file_mb_per_s": round(speed / files, 2),
        "flood_waits": len(FLOOD_EVENTS),
    }
    print(
        f"{name:<24} {result['mb_per_s']:>7.2f} MB/s total  "
        f"{result['per_file_mb_per_s']:>6.2f} MB/s/file  "
        f"{result['seconds']:>6.1f}s  flood={result['flood_waits']}",
        flush=True,
    )
    return result


def clash_request(controller, secret, method, path, body=None):
    request = urllib.request.Request(
        controller.rstrip("/") + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read()
        return json.loads(text) if text else None


TELEGRAM_PREFIXES = ("149.154.", "91.108.", "91.105.", "185.76.151.")
DC_REGIONS = {1: ["US"], 2: ["NL", "DE", "GB", "FR"], 3: ["US"], 4: ["NL", "DE", "GB", "FR"], 5: ["SG", "HK", "JP"]}


def telegram_connections(controller, secret):
    connections = clash_request(controller, secret, "GET", "/connections")["connections"] or []
    return [c for c in connections if c["metadata"].get("destinationIP", "").startswith(TELEGRAM_PREFIXES)]


def telegram_group(controller, secret):
    """(group, node) of the Clash selector currently carrying Telegram traffic."""
    for conn in telegram_connections(controller, secret):
        chains = conn.get("chains", [])
        if len(chains) >= 2:
            return chains[-1], chains[0]
    return None, None


def node_delay(controller, secret, node):
    quoted = urllib.parse.quote(node, safe="")
    try:
        return clash_request(
            controller, secret, "GET",
            f"/proxies/{quoted}/delay?timeout=3000&url="
            + urllib.parse.quote("https://www.gstatic.com/generate_204"),
        )["delay"]
    except Exception:
        return None


def pick_nodes(controller, secret, proxies, group, current, dc_ids, limit):
    """Current node plus the lowest-latency node of each region, regions
    nearest the files' data centers first."""
    order = []
    for dc_id in dc_ids:
        order += [r for r in DC_REGIONS.get(dc_id, []) if r not in order]
    order += [r for r in REGION_HINTS if r not in order]
    nodes = [
        n for n in proxies[group]["all"]
        if proxies.get(n, {}).get("type") not in ("Selector", "URLTest", "Fallback", "LoadBalance", "Direct", "Reject")
    ]
    chosen = [current]
    for region in order:
        hints = REGION_HINTS[region]
        matches = [n for n in nodes if any(h in f" {n.lower()}" for h in hints) and n not in chosen][:4]
        timed = sorted((d, n) for n in matches if (d := node_delay(controller, secret, n)) is not None)
        if timed:
            chosen.append(timed[0][1])
            print(f"  region {region}: {timed[0][1]} ({timed[0][0]} ms)")
        if len(chosen) >= limit:
            break
    return chosen


async def reset_routes(client, controller, secret):
    """Force new connections so they go through the newly selected node."""
    await close_pool(client)
    for session in list(client.media_sessions.values()):
        try:
            await session.stop()
        except Exception:
            pass
    client.media_sessions.clear()
    for conn in telegram_connections(controller, secret):
        try:
            clash_request(controller, secret, "DELETE", f"/connections/{conn['id']}")
        except Exception:
            pass


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="downloader folder with config.yaml and sessions")
    parser.add_argument("--chat", required=True)
    parser.add_argument("--plan", choices=["params", "cap", "nodes"], default="params")
    parser.add_argument("--seconds", type=int, default=30, help="duration of each case")
    parser.add_argument("--scan", type=int, default=300)
    parser.add_argument("--nodes", type=int, default=6, help="nodes to compare in the nodes plan")
    parser.add_argument("--case", default="c1 t4 x5", help="parallel case used by the nodes plan")
    parser.add_argument("--node-list", default="", help="'|'-separated node names instead of automatic choice")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("pyrogram.session.session").addHandler(FloodCounter())
    logging.getLogger("pyrogram.session.session").setLevel(logging.WARNING)

    config = YAML().load(open(os.path.join(args.base, "config.yaml"), encoding="utf-8"))
    workdir = tempfile.mkdtemp(prefix="tdl-bench-")
    shutil.copy(os.path.join(args.base, "sessions", "media_downloader.session"), workdir)
    client = pyrogram.Client(
        "media_downloader",
        api_id=config["api_id"],
        api_hash=config["api_hash"],
        proxy=dict(config["proxy"]) if config.get("proxy") else None,
        workdir=workdir,
        no_updates=True,
        # As in the downloader; Pyrogram's default of 1 serializes get_file.
        max_concurrent_transmissions=25,
    )
    results = []
    await client.start()
    try:
        me = await client.get_me()
        print(f"account premium={bool(me.is_premium)} proxy={dict(config.get('proxy') or {})}", flush=True)
        videos = await find_videos(client, args.chat, args.scan, 300 * 1024 * 1024, 5)
        dcs = sorted({FileId.decode((m.video or m.document).file_id).dc_id for m in videos})
        print(f"test files: {len(videos)} (ids {[m.id for m in videos]}), DC {dcs}", flush=True)

        if args.plan in ("params", "cap"):
            plan = PARAM_PLAN if args.plan == "params" else CAP_PLAN
            for index, case in enumerate(plan):
                results.append(await run_case(client, videos, case, args.seconds, index))
        else:
            clash = config["clash"]
            controller, secret = clash["controller"], str(clash.get("secret", ""))
            case = next(c for c in PARAM_PLAN if c[0] == args.case)
            group, current = telegram_group(controller, secret)
            print(f"telegram group={group} current node={current}")
            proxies = clash_request(controller, secret, "GET", "/proxies")["proxies"]
            if args.node_list:
                chosen = [current] + [n for n in args.node_list.split("|") if n and n != current]
            else:
                chosen = pick_nodes(controller, secret, proxies, group, current, dcs, args.nodes)
            quoted_group = urllib.parse.quote(group, safe="")
            try:
                for index, node in enumerate(chosen):
                    clash_request(controller, secret, "PUT", f"/proxies/{quoted_group}", {"name": node})
                    await reset_routes(client, controller, secret)
                    await asyncio.sleep(2)
                    print(f"--- node: {node}", flush=True)
                    for base_case in (PARAM_PLAN[1], case):
                        result = await run_case(client, videos, base_case, args.seconds, index + 20)
                        result["node"] = node
                        results.append(result)
            finally:
                clash_request(controller, secret, "PUT", f"/proxies/{quoted_group}", {"name": current})
                await reset_routes(client, controller, secret)
                print(f"restored {group} -> {current}")
    finally:
        await close_pool(client)
        await client.stop()
        shutil.rmtree(workdir, ignore_errors=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as out:
            json.dump(results, out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
