"""Download Stat"""
import asyncio
import threading
import time
from enum import Enum
from time import monotonic

from pyrogram import Client

from module.app import TaskNode


class DownloadState(Enum):
    """Download state"""

    Downloading = 1
    StopDownload = 2


_download_result: dict = {}
_download_state: DownloadState = DownloadState.Downloading
_download_result_lock = threading.RLock()
MAX_COMPLETED_RESULTS_PER_CHAT = 100
SPEED_STALE_SECONDS = 3


def get_download_result() -> dict:
    """get global download result"""
    return _download_result


def get_download_result_snapshot() -> dict:
    """Sample all displayed rates at one instant, excluding internal counters."""
    with _download_result_lock:
        now = monotonic()
        paused = _download_state is DownloadState.StopDownload
        result = {}
        for chat_id, messages in _download_result.items():
            result[chat_id] = {}
            for message_id, value in messages.items():
                item = {
                    key: field
                    for key, field in value.items()
                    if not key.startswith("_")
                }
                stale = now - value.get("_progress_time", now) >= SPEED_STALE_SECONDS
                item["download_speed"] = (
                    0
                    if paused or stale or value.get("terminal", False)
                    else max(int(value.get("download_speed") or 0), 0)
                )
                result[chat_id][message_id] = item
        return result


def get_total_download_speed() -> int:
    """Use the same active-file rates as the download list, not a second meter."""
    return sum(
        item["download_speed"]
        for messages in get_download_result_snapshot().values()
        for item in messages.values()
        if not item.get("terminal", False)
    )


def get_active_download_count() -> int:
    """Return active download item count."""
    active_count = 0
    with _download_result_lock:
        for messages in _download_result.values():
            for value in messages.values():
                if not value.get("terminal", False):
                    active_count += 1
    return active_count


def remove_download_status(chat_id, message_id: int):
    """Remove a terminal download from the live progress registry."""
    with _download_result_lock:
        messages = _download_result.get(chat_id)
        if not messages:
            return

        messages.pop(message_id, None)
        if not messages:
            _download_result.pop(chat_id, None)


def finish_download_status(chat_id, message_id: int, succeeded: bool):
    """Finalize live progress while retaining bounded successful Web history."""
    with _download_result_lock:
        messages = _download_result.get(chat_id)
        if not messages or message_id not in messages:
            return

        if not succeeded:
            remove_download_status(chat_id, message_id)
            return

        value = messages[message_id]
        if not value["total_size"]:
            value["total_size"] = value["down_byte"]
        value["down_byte"] = value["total_size"]
        value["download_speed"] = 0
        value["terminal"] = True

        completed_ids = [
            item_id
            for item_id, item in messages.items()
            if item.get("terminal", False)
        ]
        for old_id in completed_ids[:-MAX_COMPLETED_RESULTS_PER_CHAT]:
            messages.pop(old_id, None)


def get_download_state() -> DownloadState:
    """get download state"""
    return _download_state


# pylint: disable = W0603
def set_download_state(state: DownloadState):
    """set download state"""
    global _download_state
    with _download_result_lock:
        if state is not _download_state:
            now = monotonic()
            for messages in _download_result.values():
                for value in messages.values():
                    value["download_speed"] = 0
                    value["_sample_time"] = now
                    value["_sample_bytes"] = value["down_byte"]
                    value["_has_sample"] = False
        _download_state = state


async def update_download_status(
    down_byte: int,
    total_size: int,
    message_id: int,
    file_name: str,
    start_time: float,
    node: TaskNode,
    client: Client,
):
    """update_download_status"""
    if node.is_stop_transmission:
        client.stop_transmission()

    chat_id = node.chat_id

    while get_download_state() == DownloadState.StopDownload:
        if node.is_stop_transmission:
            client.stop_transmission()
        await asyncio.sleep(1)

    with _download_result_lock:
        now = monotonic()
        cur_time = time.time()
        messages = _download_result.setdefault(chat_id, {})
        value = messages.get(message_id)
        if (
            not value
            or "_sample_time" not in value
            or value.get("terminal", False)
            or value.get("task_id") != node.task_id
            or value.get("start_time") != start_time
            or down_byte <= value["down_byte"]
        ):
            # The first callback establishes the resume offset. Bytes already on
            # disk (and a previous attempt's progress) are not network traffic.
            messages[message_id] = {
                "down_byte": down_byte,
                "total_size": total_size,
                "file_name": file_name,
                "start_time": start_time,
                "end_time": cur_time,
                "download_speed": 0,
                "task_id": node.task_id,
                "terminal": False,
                "_sample_time": now,
                "_sample_bytes": down_byte,
                "_progress_time": now,
                "_has_sample": False,
            }
            return

        # Each file uses its own one-second sample; totals sum those exact
        # samples. Monotonic time avoids spikes after system-clock changes.
        elapsed = now - value["_sample_time"]
        # Show a useful initial rate for files finishing in under a second,
        # without including their pre-existing resume offset.
        if elapsed > 0 and (elapsed >= 1 or not value.get("_has_sample", False)):
            value["download_speed"] = max(
                int((down_byte - value["_sample_bytes"]) / max(elapsed, 0.001)), 0
            )
            if elapsed >= 1:
                value["_sample_time"] = now
                value["_sample_bytes"] = down_byte
                value["_has_sample"] = True
        value.update(
            down_byte=down_byte,
            total_size=total_size,
            end_time=cur_time,
            _progress_time=now,
        )
