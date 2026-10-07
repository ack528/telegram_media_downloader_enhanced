import asyncio
import random
import unittest
from unittest import mock

from pyrogram import raw
from pyrogram.file_id import FileId, FileType

from module.fast_download import (
    PART_ATTEMPTS,
    PART_SIZE,
    CdnRedirect,
    iter_file_parallel,
)

_real_sleep = asyncio.sleep


async def fake_sleep(delay, *args):
    """Skip retry back-off but keep the fake network latency."""
    await _real_sleep(min(delay, 0.01), *args)


def _file_id():
    return FileId(
        file_type=FileType.VIDEO,
        dc_id=5,
        media_id=1,
        access_hash=2,
        file_reference=b"ref",
    )


class FakeSession:
    """Serves parts of an in-memory file with random latency."""

    def __init__(self, data, log, cdn=False, fail_times=0, shared=None):
        self.data = data
        self.log = log
        self.cdn = cdn
        self.fail_times = fail_times
        # Counts requests in flight across sessions: {"now": n, "peak": n}.
        self.shared = shared if shared is not None else {"now": 0, "peak": 0}
        self.in_flight = 0
        self.calls = 0

    async def invoke(self, query, **_kwargs):
        self.calls += 1
        self.in_flight += 1
        self.shared["now"] += 1
        self.shared["peak"] = max(self.shared["peak"], self.shared["now"])
        self.log.append(("start", query.offset))
        try:
            await asyncio.sleep(random.uniform(0, 0.01))
            if self.fail_times:
                self.fail_times -= 1
                raise TimeoutError("Request timed out")
            if self.cdn:
                return raw.types.upload.FileCdnRedirect(
                    dc_id=203, file_token=b"", encryption_key=b"", encryption_iv=b"", file_hashes=[]
                )
            chunk = self.data[query.offset : query.offset + query.limit]
            return raw.types.upload.File(
                type=raw.types.storage.FilePartial(), mtime=0, bytes=chunk
            )
        finally:
            self.in_flight -= 1
            self.shared["now"] -= 1


async def _collect(
    data, sessions, offset_parts=0, threads=4, size=None, limiter=None
):
    progress = []
    out = []
    async for chunk in iter_file_parallel(
        None,
        _file_id(),
        len(data) if size is None else size,
        offset_parts,
        threads=threads,
        sessions=sessions,
        limiter=limiter,
        progress=lambda done, total: progress.append(done),
    ):
        out.append(chunk)
    return b"".join(out), progress


class FastDownloadTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 5.5 parts, so the last part is short.
        self.data = bytes(random.getrandbits(8) for _ in range(int(PART_SIZE * 5.5)))

    async def test_parts_arrive_in_order_across_connections(self):
        log = []
        sessions = [FakeSession(self.data, log) for _ in range(3)]
        result, progress = await _collect(self.data, sessions, threads=4)
        self.assertEqual(result, self.data)
        self.assertEqual(progress[-1], len(self.data))
        self.assertEqual(progress, sorted(progress))
        # Six parts round-robin over three connections: two requests each.
        self.assertEqual([s.calls for s in sessions], [2, 2, 2])

    async def test_resume_from_part_offset(self):
        result, _ = await _collect(self.data, [FakeSession(self.data, [])], offset_parts=2)
        self.assertEqual(result, self.data[2 * PART_SIZE :])

    async def test_unknown_size_stops_at_short_part(self):
        result, _ = await _collect(self.data, [FakeSession(self.data, [])], size=0)
        self.assertEqual(result, self.data)

    async def test_keeps_threads_in_flight(self):
        log = []
        session = FakeSession(self.data, log)
        await _collect(self.data, [session], threads=4)
        first_starts = [entry for entry in log[:4] if entry[0] == "start"]
        self.assertEqual(len(first_starts), 4)

    async def test_downloads_share_the_in_flight_cap(self):
        shared = {"now": 0, "peak": 0}
        sessions = [FakeSession(self.data, [], shared=shared) for _ in range(2)]
        limiter = asyncio.Semaphore(3)
        results = await asyncio.gather(
            *(
                _collect(self.data, sessions, threads=4, limiter=limiter)
                for _ in range(3)
            )
        )
        for result, _ in results:
            self.assertEqual(result, self.data)
        self.assertEqual(shared["peak"], 3)

    async def test_timed_out_part_is_retried_on_next_connection(self):
        stuck = FakeSession(self.data, [], fail_times=1)
        healthy = FakeSession(self.data, [])
        with mock.patch("module.fast_download.asyncio.sleep", fake_sleep):
            result, _ = await _collect(self.data, [stuck, healthy], threads=1)
        self.assertEqual(result, self.data)
        # Part 0 failed on the first connection, then went to the second.
        self.assertEqual((stuck.calls, healthy.calls), (3, 4))

    async def test_gives_up_after_repeated_timeouts(self):
        session = FakeSession(self.data, [], fail_times=PART_ATTEMPTS)
        with mock.patch("module.fast_download.asyncio.sleep", fake_sleep):
            with self.assertRaises(TimeoutError):
                await _collect(self.data, [session], threads=1)
        self.assertEqual(session.calls, PART_ATTEMPTS)

    async def test_cdn_redirect_is_reported(self):
        with self.assertRaises(CdnRedirect):
            await _collect(self.data, [FakeSession(self.data, [], cdn=True)])

    async def test_closing_early_cancels_pending_requests(self):
        session = FakeSession(self.data, [])
        stream = iter_file_parallel(
            None, _file_id(), len(self.data), 0, threads=4, sessions=[session]
        )
        await stream.__anext__()
        await stream.aclose()
        await asyncio.sleep(0.02)
        self.assertEqual(session.in_flight, 0)


if __name__ == "__main__":
    unittest.main()
