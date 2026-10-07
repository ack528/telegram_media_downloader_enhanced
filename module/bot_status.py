"""Rendering of the bot's live task status message (Telegram HTML).

Card layout (Chinese UI); each file is a Telegram quote block:

    📥 任务 #1 · ixsnv
    下载中 · 187/195 · 95%
    ⚡ 2.3 MB/s · 💾 12.4 GB
    ✅ 180  ⏭ 7

    ┃ 城市夜景延时摄影…版本.mp4
    ┃ ▰▰▰▰▰▰▰▰▰▱ 98%
    ┃ 181 KB/s · 剩余 3:51

    19:37:52 更新

While the chat is still being scanned the second line tracks the message
range instead (``下载中 · 消息 1124/2100 · 53%``).  Lines and counters with
nothing to report are left out.

Everything user-controlled (chat titles, file names) is HTML-escaped.
"""

import html
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from module.language import _t

FILE_BAR_WIDTH = 10
FILE_NAME_WIDTH = 30
MAX_FILES = 5


@dataclass
class FileProgress:
    """One in-flight transfer shown in the status message."""

    message_id: int
    name: str
    total: int
    done: int
    speed: float


@dataclass
class CloudUpload:
    """An rclone upload; rclone reports preformatted strings."""

    message_id: int
    name: str
    total: str
    percentage: str
    speed: str
    eta: str


def human_bytes(value: Optional[float]) -> str:
    """Compact size: 968 KB, 2.19 GB, 12.5 GB."""
    value = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    if unit == 0:
        return f"{int(value)} B"
    if value < 10:
        return f"{value:.2f} {units[unit]}"
    if value < 100:
        return f"{value:.1f} {units[unit]}"
    return f"{value:.0f} {units[unit]}"


def human_speed(value: Optional[float]) -> str:
    """Compact transfer speed."""
    return f"{human_bytes(value)}/s"


def progress_bar(ratio: float, width: int) -> str:
    """▰▱ bar; always shows progress once it has started."""
    ratio = min(max(ratio, 0.0), 1.0)
    filled = int(round(ratio * width))
    if 0 < ratio < 1:
        filled = min(max(filled, 1), width - 1)
    return "▰" * filled + "▱" * (width - filled)


def format_eta(seconds: Optional[float]) -> str:
    """Language-neutral H:MM:SS / M:SS."""
    if seconds is None or seconds < 0 or seconds > 99 * 3600:
        return ""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _clip_width(text: str, width: int, from_end: bool = False) -> str:
    """Longest prefix (or suffix) of ``text`` within ``width`` columns."""
    chars = reversed(text) if from_end else text
    out, used = [], 0
    for ch in chars:
        used += _display_width(ch)
        if used > width:
            break
        out.append(ch)
    return "".join(reversed(out)) if from_end else "".join(out)


def display_file_name(path: str, message_id: int, width: int = FILE_NAME_WIDTH) -> str:
    """Readable file name: drop the redundant "<message id> - " prefix and
    shorten the middle so both the start and the extension stay visible."""
    name = os.path.basename(path or "")
    name = re.sub(rf"^{message_id}\s*[-_]\s*(?=.)", "", name)
    stem, ext = os.path.splitext(name)
    if stem.startswith(".") and not ext:
        # "123 - .mp4" (media without a file name) leaves only the extension.
        stem, ext = "", stem
    if not stem:
        return f"{_t('Untitled')}{ext}"
    if _display_width(name) <= width:
        return name
    budget = max(width - _display_width(ext) - 1, 6)
    head = _clip_width(stem, budget * 2 // 3)
    tail = _clip_width(stem, budget - _display_width(head), from_end=True)
    return f"{head}…{tail}{ext}"


def _e(text) -> str:
    return html.escape(str(text), quote=False)


def _state_label(node, paused: bool, offline: bool, active: bool) -> str:
    if node.is_stop_transmission:
        return _t("Stopped")
    if node.is_finish():
        return _t("Completed")
    if offline:
        return _t("Waiting for network")
    if paused:
        return _t("Paused")
    if not node.scan_finished and not active:
        return _t("Scanning")
    return _t("In progress")


def _status_line(node, state: str) -> str:
    """State plus progress: files once the scan is done, else the message
    range scanned so far."""
    done, total = node.total_download_task, node.total_task
    if node.scan_finished:
        if total:
            return f"{state} · {done}/{total} · {int(done / total * 100)}%"
        return state
    position = getattr(node, "scan_message_id", 0)
    if position and node.end_offset_id:
        start = node.start_offset_id or 0
        ratio = (position - start) / max(node.end_offset_id - start, 1)
        return f"{state} · " + _t("Message {pos}/{end} · {pct}%").format(
            pos=position, end=node.end_offset_id, pct=int(min(max(ratio, 0), 1) * 100)
        )
    if position:
        return f"{state} · " + _t("Scanned to message {pos}").format(pos=position)
    return state


def _speed_line(node, software_speed, clash_speed, clash_enabled) -> str:
    """Download speed; the proxy's total only when other traffic shares it."""
    proxy = clash_speed if clash_enabled else None
    if software_speed is None:
        software_speed, proxy = proxy, None
    parts = [f"⚡ {human_speed(software_speed)}"]
    if proxy is not None and proxy - (software_speed or 0) > max(
        (software_speed or 0) * 0.2, 256 * 1024
    ):
        parts.append(_t("Proxy {speed}").format(speed=human_speed(proxy)))
    if node.total_download_byte:
        parts.append(f"💾 {human_bytes(node.total_download_byte)}")
    return " · ".join(parts)


def _card(name: str, ratio: float, detail: str) -> str:
    """One file as a Telegram quote block: name, bar, speed line."""
    return "\n".join(
        [
            f"<blockquote>{_e(name)}",
            f"{progress_bar(ratio, FILE_BAR_WIDTH)} {int(ratio * 100)}%",
            f"{detail}</blockquote>",
        ]
    )


def _file_card(item: FileProgress, icon: str = "") -> str:
    ratio = item.done / item.total if item.total else 0.0
    parts = [f"{icon}{human_speed(item.speed)}"]
    if item.speed > 0 and item.total:
        eta = format_eta((item.total - item.done) / item.speed)
        if eta:
            parts.append(_t("{eta} left").format(eta=eta))
    return _card(display_file_name(item.name, item.message_id), ratio, " · ".join(parts))


def _cloud_card(item: CloudUpload) -> str:
    percent = re.sub(r"[^\d.]", "", item.percentage) or "0"
    parts = [f"☁️ {_e(item.speed)}"]
    if item.eta:
        parts.append(_e(_t("{eta} left").format(eta=item.eta)))
    return _card(
        display_file_name(item.name, item.message_id), float(percent) / 100, " · ".join(parts)
    )


# pylint: disable = R0913, R0914
def render_task_status(
    node,
    *,
    downloads: List[FileProgress],
    uploads: List[FileProgress],
    cloud_uploads: List[CloudUpload],
    software_speed: Optional[float],
    clash_speed: Optional[float],
    clash_enabled: bool,
    paused: bool = False,
    offline: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """Build the HTML status message for one task node (card layout)."""
    now = now or datetime.now()
    title = f"{_t('Task')} #{node.task_id}"
    chat_title = getattr(node, "chat_title", "")
    if chat_title:
        title += f" · {chat_title}"
    lines: List[str] = [f"📥 <b>{_e(title)}</b>"]

    state = _state_label(node, paused, offline, active=bool(downloads or uploads))
    lines.append(_e(_status_line(node, state)))
    lines.append(_e(_speed_line(node, software_speed, clash_speed, clash_enabled)))
    counters = [
        f"{icon} {count}"
        for icon, count in (
            ("✅", node.success_download_task),
            ("⏭", node.skip_download_task),
            ("❌", node.failed_download_task),
        )
        if count
    ]
    if counters:
        lines.append("  ".join(counters))
    if node.upload_telegram_chat_id:
        lines.append(
            f"↪️ {_e(_t('Forward'))} {node.success_forward_task}/{node.total_forward_task}"
            f"  ❌ {node.failed_forward_task}  ⏭ {node.skip_forward_task}"
        )
    if node.upload_success_count:
        lines.append(f"☁️ {_e(_t('Upload'))} ✅ {node.upload_success_count}")

    cards = [_file_card(item) for item in downloads]
    cards += [_file_card(item, icon="⏫ ") for item in uploads]
    cards += [_cloud_card(item) for item in cloud_uploads]
    for card in cards:
        lines += ["", card]

    lines += ["", f"<i>{_e(_t('Updated {time}').format(time=now.strftime('%H:%M:%S')))}</i>"]
    return "\n".join(lines)
