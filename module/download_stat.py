"""Download Stat"""
import asyncio
import threading
import time
from enum import Enum

from pyrogram import Client

from module.app import TaskNode


class DownloadState(Enum):
    """Download state"""

    Downloading = 1
    StopDownload = 2


_download_result: dict = {}
_total_download_speed: int = 0
_total_download_size: int = 0
_last_download_time: float = time.time()
_download_state: DownloadState = DownloadState.Downloading
_download_result_lock = threading.RLock()
MAX_COMPLETED_RESULTS_PER_CHAT = 100


def get_download_result() -> dict:
    """get global download result"""
    return _download_result


def get_download_result_snapshot() -> dict:
    """Return a thread-safe copy for the Flask worker thread."""
    with _download_result_lock:
        return {
            chat_id: {
                message_id: dict(value)
                for message_id, value in messages.items()
            }
            for chat_id, messages in _download_result.items()
        }


def get_total_download_speed() -> int:
    """get total download speed"""
    if time.time() - _last_download_time > 3:
        return 0
    return _total_download_speed


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
    cur_time = time.time()
    # pylint: disable = W0603
    global _total_download_speed
    global _total_download_size
    global _last_download_time

    if node.is_stop_transmission:
        client.stop_transmission()

    chat_id = node.chat_id

    while get_download_state() == DownloadState.StopDownload:
        if node.is_stop_transmission:
            client.stop_transmission()
        await asyncio.sleep(1)

    with _download_result_lock:
        if not _download_result.get(chat_id):
            _download_result[chat_id] = {}

        if _download_result[chat_id].get(message_id):
            last_download_byte = _download_result[chat_id][message_id]["down_byte"]
            last_time = _download_result[chat_id][message_id]["end_time"]
            download_speed = _download_result[chat_id][message_id]["download_speed"]
            each_second_total_download = _download_result[chat_id][message_id][
                "each_second_total_download"
            ]
            end_time = _download_result[chat_id][message_id]["end_time"]

            _total_download_size += down_byte - last_download_byte
            each_second_total_download += down_byte - last_download_byte

            if cur_time - last_time >= 1.0:
                download_speed = int(each_second_total_download / (cur_time - last_time))
                end_time = cur_time
                each_second_total_download = 0

            download_speed = max(download_speed, 0)

            _download_result[chat_id][message_id]["down_byte"] = down_byte
            _download_result[chat_id][message_id]["end_time"] = end_time
            _download_result[chat_id][message_id]["download_speed"] = download_speed
            _download_result[chat_id][message_id][
                "each_second_total_download"
            ] = each_second_total_download
        else:
            each_second_total_download = down_byte
            elapsed = max(cur_time - start_time, 0.001)
            _download_result[chat_id][message_id] = {
                "down_byte": down_byte,
                "total_size": total_size,
                "file_name": file_name,
                "start_time": start_time,
                "end_time": cur_time,
                "download_speed": down_byte / elapsed,
                "each_second_total_download": each_second_total_download,
                "task_id": node.task_id,
                "terminal": False,
            }
            _total_download_size += down_byte

        if cur_time - _last_download_time >= 1.0:
            # update speed
            _total_download_speed = int(
                _total_download_size / (cur_time - _last_download_time)
            )
            _total_download_speed = max(_total_download_speed, 0)
            _total_download_size = 0
            _last_download_time = cur_time
