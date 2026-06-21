"""Downloads media from telegram."""
import asyncio
import logging
import os
import shutil
import sys
import time
from typing import List, Optional, Tuple, Union

import pyrogram
from pyrogram.file_id import FileId
from loguru import logger
from pyrogram.types import Audio, Document, Photo, Video, VideoNote, Voice
from rich.logging import RichHandler

from module.app import Application, ChatDownloadConfig, DownloadStatus, TaskNode
from module.bot import get_download_bot, start_download_bot, stop_download_bot
from module.clash_controller import ClashController
from module.download_stat import (
    get_active_download_count,
    get_total_download_speed,
    update_download_status,
)
from module.get_chat_history_v2 import get_chat_history_v2
from module.language import _t
from module.network_watchdog import bump_network_epoch, get_network_epoch
from module.pyrogram_extension import (
    HookClient,
    fetch_message,
    get_extension,
    record_download_status,
    report_bot_download_status,
    set_max_concurrent_transmissions,
    set_meta_data,
    set_status_clash_config,
    update_cloud_upload_stat,
    upload_telegram_chat,
)
from module.web import init_web
from utils.format import format_byte, truncate_filename, validate_title
from utils.log import LogFilter, disable_quick_edit_mode
from utils.meta import print_meta
from utils.meta_data import MetaData


def _is_usable_console_stream(stream) -> bool:
    """Return True only for real streams that can be used by Rich/loguru."""
    if stream is None:
        return False
    try:
        stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _configure_startup_logging():
    """Configure logging safely for console and GUI/no-console builds."""
    logger.remove()
    has_console_stream = _is_usable_console_stream(sys.stderr)
    sink = sys.stderr if has_console_stream else (lambda _: None)
    logger.add(
        sink,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
        filter=lambda record: record["extra"].get("console")
        or record["level"].no >= logger.level("WARNING").no,
    )

    handler = RichHandler() if has_console_stream else logging.NullHandler()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[handler],
    )


_configure_startup_logging()

disable_quick_edit_mode()

CONFIG_NAME = "config.yaml"
DATA_FILE_NAME = "data.yaml"
APPLICATION_NAME = "media_downloader"
app = Application(CONFIG_NAME, DATA_FILE_NAME, APPLICATION_NAME)

queue: asyncio.Queue = asyncio.Queue()
RETRY_TIME_OUT = 3
DOWNLOAD_RETRY_COUNT = 5
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
LOW_SPEED_MONITOR_INTERVAL = 5
DOWNLOAD_HEARTBEAT_INTERVAL = 60
_clash_switch_event = asyncio.Event()
_clash_switch_reason: Optional[str] = None

logging.getLogger("pyrogram.session.session").addFilter(LogFilter())
logging.getLogger("pyrogram.client").addFilter(LogFilter())
logging.getLogger("pyrogram").addFilter(LogFilter())

logging.getLogger("pyrogram").setLevel(logging.WARNING)


def _clash_low_speed_threshold() -> int:
    """Return the current Clash low-speed threshold in bytes per second."""
    try:
        return int(app.clash_config.get("low_speed_kb", 100)) * 1024
    except (TypeError, ValueError):
        return 100 * 1024


def _downloads_are_healthy_for_clash_switch() -> Tuple[bool, int, int, int]:
    """Return whether active downloads are healthy enough to skip node switching."""
    active_count = get_active_download_count()
    speed = get_total_download_speed()
    low_speed_bytes = _clash_low_speed_threshold()
    return active_count > 0 and speed >= low_speed_bytes, active_count, speed, low_speed_bytes


def request_clash_switch(reason: str):
    """Ask the Clash monitor to switch nodes because network requests are failing."""
    global _clash_switch_reason
    if not app.clash_config.get("enabled", True):
        return

    healthy, active_count, speed, low_speed_bytes = _downloads_are_healthy_for_clash_switch()
    if healthy:
        logger.warning(
            "Ignored Clash switch request while downloads are healthy: reason={}, active={}, speed={}/s, threshold={}/s",
            reason,
            active_count,
            format_byte(speed),
            format_byte(low_speed_bytes),
        )
        return

    _clash_switch_reason = reason
    _clash_switch_event.set()
    logger.warning("Network issue detected; scheduled Clash node switch: {}", reason)


def _check_download_finish(media_size: int, download_path: str, ui_file_name: str):
    """Check download task if finish

    Parameters
    ----------
    media_size: int
        The size of the downloaded resource
    download_path: str
        Resource download hold path
    ui_file_name: str
        Really show file name

    """
    download_size = os.path.getsize(download_path)
    if media_size == download_size:
        logger.bind(console=True).success(
            f"{_t('Successfully downloaded')} - {ui_file_name}"
        )
    else:
        logger.warning(
            f"{_t('Media downloaded with wrong size')}: "
            f"{download_size}, {_t('actual')}: "
            f"{media_size}, {_t('file name')}: {ui_file_name}"
        )
        os.remove(download_path)
        raise pyrogram.errors.exceptions.bad_request_400.BadRequest()


def _move_to_download_path(temp_download_path: str, download_path: str):
    """Move file to download path

    Parameters
    ----------
    temp_download_path: str
        Temporary download path

    download_path: str
        Download path

    """

    directory, _ = os.path.split(download_path)
    os.makedirs(directory, exist_ok=True)
    shutil.move(temp_download_path, download_path)


def _temp_download_path(temp_file_name: str) -> str:
    """Return the resumable temporary download path."""
    return f"{temp_file_name}.temp"


def _remove_file_if_exists(file_path: str):
    """Remove a stale helper file if it exists."""
    if os.path.exists(file_path):
        os.remove(file_path)


def _cleanup_stale_temp_files(temp_file_name: str):
    """Clean temp files that are no longer needed after a final file exists."""
    _remove_file_if_exists(temp_file_name)
    _remove_file_if_exists(_temp_download_path(temp_file_name))


def _move_partial_to_resume(
    partial_path: str, temp_file_name: str, media_size: int
) -> int:
    """Move a partial file into the resumable temp path, preserving more progress."""
    resume_path = _temp_download_path(temp_file_name)
    partial_size = os.path.getsize(partial_path)
    resume_size = os.path.getsize(resume_path) if os.path.exists(resume_path) else 0
    resume_is_valid = bool(media_size and 0 < resume_size <= media_size)

    if resume_is_valid and resume_size >= partial_size:
        os.remove(partial_path)
        return resume_size

    os.makedirs(os.path.dirname(resume_path), exist_ok=True)
    os.replace(partial_path, resume_path)
    return partial_size


def _align_resume_size(file_path: str, media_size: int) -> int:
    """Align an existing temp file to Telegram's 1MB download chunks."""
    if not os.path.exists(file_path):
        return 0

    file_size = os.path.getsize(file_path)
    if media_size and file_size > media_size:
        logger.warning("Discard invalid oversized temp file: {}", file_path)
        os.remove(file_path)
        return 0

    aligned_size = (file_size // DOWNLOAD_CHUNK_SIZE) * DOWNLOAD_CHUNK_SIZE
    if aligned_size != file_size:
        with open(file_path, "ab") as temp_file:
            temp_file.truncate(aligned_size)
    return aligned_size


def _recover_existing_download(
    file_name: str, temp_file_name: str, media_size: int, ui_file_name: str
) -> Optional[DownloadStatus]:
    """Recover finished or partial files left by an interrupted run."""
    if _is_exist(file_name):
        file_size = os.path.getsize(file_name)
        if media_size == 0 or file_size == media_size:
            logger.debug(
                f"id file {ui_file_name} {_t('already download,download skipped')}.\n"
            )
            _cleanup_stale_temp_files(temp_file_name)
            return DownloadStatus.SkipDownload

        if media_size and 0 < file_size < media_size:
            resume_size = _move_partial_to_resume(file_name, temp_file_name, media_size)
            logger.warning(
                "Resume partial final file: {} ({}/{})",
                ui_file_name,
                resume_size,
                media_size,
            )
        else:
            logger.warning(
                "Remove invalid existing file: {} ({}/{})",
                ui_file_name,
                file_size,
                media_size,
            )
            os.remove(file_name)

    if _is_exist(temp_file_name):
        temp_size = os.path.getsize(temp_file_name)
        if media_size == 0 or temp_size == media_size:
            _check_download_finish(media_size, temp_file_name, ui_file_name)
            _move_to_download_path(temp_file_name, file_name)
            return DownloadStatus.SuccessDownload

        if media_size and 0 < temp_size < media_size:
            _move_partial_to_resume(temp_file_name, temp_file_name, media_size)
        else:
            os.remove(temp_file_name)

    return None


def _check_timeout(retry: int, _: int):
    """Check if message download timeout, then add message id into failed_ids

    Parameters
    ----------
    retry: int
        Retry download message times

    message_id: int
        Try to download message 's id

    """
    if retry == 2:
        return True
    return False


def _can_download(_type: str, file_formats: dict, file_format: Optional[str]) -> bool:
    """
    Check if the given file format can be downloaded.

    Parameters
    ----------
    _type: str
        Type of media object.
    file_formats: dict
        Dictionary containing the list of file_formats
        to be downloaded for `audio`, `document` & `video`
        media types
    file_format: str
        Format of the current file to be downloaded.

    Returns
    -------
    bool
        True if the file format can be downloaded else False.
    """
    if _type in ["audio", "document", "video"]:
        allowed_formats: list = file_formats[_type]
        if not file_format in allowed_formats and allowed_formats[0] != "all":
            return False
    return True


def _is_exist(file_path: str) -> bool:
    """
    Check if a file exists and it is not a directory.

    Parameters
    ----------
    file_path: str
        Absolute path of the file to be checked.

    Returns
    -------
    bool
        True if the file exists else False.
    """
    return not os.path.isdir(file_path) and os.path.exists(file_path)


# pylint: disable = R0912


async def _get_media_meta(
    chat_id: Union[int, str],
    message: pyrogram.types.Message,
    media_obj: Union[Audio, Document, Photo, Video, VideoNote, Voice],
    _type: str,
) -> Tuple[str, str, Optional[str]]:
    """Extract file name and file id from media object.

    Parameters
    ----------
    media_obj: Union[Audio, Document, Photo, Video, VideoNote, Voice]
        Media object to be extracted.
    _type: str
        Type of media object.

    Returns
    -------
    Tuple[str, str, Optional[str]]
        file_name, file_format
    """
    if _type in ["audio", "document", "video"]:
        # pylint: disable = C0301
        file_format: Optional[str] = media_obj.mime_type.split("/")[-1]  # type: ignore
    else:
        file_format = None

    file_name = None
    temp_file_name = None
    dirname = validate_title(f"{chat_id}")
    if message.chat and message.chat.title:
        dirname = validate_title(f"{message.chat.title}")

    if message.date:
        datetime_dir_name = message.date.strftime(app.date_format)
    else:
        datetime_dir_name = "0"

    if _type in ["voice", "video_note"]:
        # pylint: disable = C0209
        file_format = media_obj.mime_type.split("/")[-1]  # type: ignore
        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)
        file_name = "{} - {}_{}.{}".format(
            message.id,
            _type,
            media_obj.date.isoformat(),  # type: ignore
            file_format,
        )
        file_name = validate_title(file_name)
        temp_file_name = os.path.join(app.temp_save_path, dirname, file_name)

        file_name = os.path.join(file_save_path, file_name)
    else:
        file_name = getattr(media_obj, "file_name", None)
        caption = getattr(message, "caption", None)

        file_name_suffix = ".unknown"
        if not file_name:
            file_name_suffix = get_extension(
                media_obj.file_id, getattr(media_obj, "mime_type", "")
            )
        else:
            # file_name = file_name.split(".")[0]
            _, file_name_without_suffix = os.path.split(os.path.normpath(file_name))
            file_name, file_name_suffix = os.path.splitext(file_name_without_suffix)
            if not file_name_suffix:
                file_name_suffix = get_extension(
                    media_obj.file_id, getattr(media_obj, "mime_type", "")
                )

        if caption:
            caption = validate_title(caption)
            app.set_caption_name(chat_id, message.media_group_id, caption)
            app.set_caption_entities(
                chat_id, message.media_group_id, message.caption_entities
            )
        else:
            caption = app.get_caption_name(chat_id, message.media_group_id)

        if not file_name and message.photo:
            file_name = f"{message.photo.file_unique_id}"

        gen_file_name = (
            app.get_file_name(message.id, file_name, caption) + file_name_suffix
        )

        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)

        temp_file_name = os.path.join(app.temp_save_path, dirname, gen_file_name)

        file_name = os.path.join(file_save_path, gen_file_name)
    return truncate_filename(file_name), truncate_filename(temp_file_name), file_format


async def add_download_task(
    message: pyrogram.types.Message,
    node: TaskNode,
):
    """Add Download task"""
    if message.empty:
        return False
    node.is_running = True
    node.download_status[message.id] = DownloadStatus.Downloading
    app.mark_download_pending(node, message.id)
    await queue.put((message, node))
    if node.total_task == 0:
        logger.bind(console=True).info(
            "任务 {} 已发现首个可下载媒体，开始加入下载队列并启动下载。",
            node.task_id,
        )
    node.total_task += 1
    logger.debug(
        "Queued download task: task_id={}, chat_id={}, message_id={}, queue_size={}",
        node.task_id,
        node.chat_id,
        message.id,
        queue.qsize(),
    )
    app.update_config(True)
    return True


async def wait_for_scan_prefetch_window(
    chat_download_config: ChatDownloadConfig,
    node: TaskNode,
):
    """Limit how far message scanning can run ahead of active downloads."""
    prefetch_limit = int(getattr(app, "scan_prefetch_limit", 0) or 0)
    if prefetch_limit <= 0:
        return

    notified = False
    while app.is_running and not node.is_stop_transmission:
        unfinished_count = node.total_task - chat_download_config.finish_task
        if unfinished_count < prefetch_limit:
            return

        if not notified:
            logger.bind(console=True).info(
                "任务 {} 已达到预取上限 {}，等待下载完成后继续扫描。",
                node.task_id,
                prefetch_limit,
            )
            notified = True
        await asyncio.sleep(1)


async def save_msg_to_file(
    app, chat_id: Union[int, str], message: pyrogram.types.Message
):
    """Write message text into file"""
    dirname = validate_title(
        message.chat.title if message.chat and message.chat.title else str(chat_id)
    )
    datetime_dir_name = message.date.strftime(app.date_format) if message.date else "0"

    file_save_path = app.get_file_save_path("msg", dirname, datetime_dir_name)
    file_name = os.path.join(
        app.temp_save_path,
        file_save_path,
        f"{app.get_file_name(message.id, None, None)}.txt",
    )

    os.makedirs(os.path.dirname(file_name), exist_ok=True)

    if _is_exist(file_name):
        return DownloadStatus.SkipDownload, None

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(message.text or "")

    return DownloadStatus.SuccessDownload, file_name


async def _download_media_with_resume(
    client: pyrogram.client.Client,
    media_obj,
    temp_file_name: str,
    media_size: int,
    progress,
    progress_args: tuple,
) -> str:
    """Download media and keep partial temp files for future resume."""
    os.makedirs(os.path.dirname(temp_file_name), exist_ok=True)
    temp_download_path = _temp_download_path(temp_file_name)
    resume_size = _align_resume_size(temp_download_path, media_size)

    if media_size and resume_size == media_size:
        shutil.move(temp_download_path, temp_file_name)
        return temp_file_name

    if resume_size:
        logger.info(
            "Resuming download from {} MB: {}",
            round(resume_size / DOWNLOAD_CHUNK_SIZE, 2),
            temp_file_name,
        )

    file_id_obj = FileId.decode(media_obj.file_id)
    offset = resume_size // DOWNLOAD_CHUNK_SIZE

    network_epoch = get_network_epoch()
    file_stream = client.get_file(
        file_id_obj,
        media_size,
        0,
        offset,
        progress,
        progress_args,
    )

    try:
        with open(temp_download_path, "ab") as temp_file:
            while True:
                if get_network_epoch() != network_epoch:
                    raise IOError("network route changed, restarting resumable download")

                try:
                    chunk = await asyncio.wait_for(
                        file_stream.__anext__(),
                        timeout=app.download_stall_timeout,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"download stalled for {app.download_stall_timeout} seconds"
                    ) from exc

                if chunk:
                    temp_file.write(chunk)
    finally:
        await file_stream.aclose()

    if media_size:
        downloaded_size = os.path.getsize(temp_download_path)
        if downloaded_size != media_size:
            raise IOError(
                f"incomplete download: {downloaded_size}/{media_size} bytes"
            )

    shutil.move(temp_download_path, temp_file_name)
    return temp_file_name


async def download_task(
    client: pyrogram.Client, message: pyrogram.types.Message, node: TaskNode
):
    """Download and Forward media"""
    task_started_at = time.time()
    logger.debug(
        "Download task started: task_id={}, chat_id={}, message_id={}",
        node.task_id,
        node.chat_id,
        message.id,
    )

    download_status, file_name = await download_media(
        client, message, app.media_types, app.file_formats, node
    )

    if app.enable_download_txt and message.text and not message.media:
        download_status, file_name = await save_msg_to_file(app, node.chat_id, message)

    app.set_download_id(node, message.id, download_status)

    node.download_status[message.id] = download_status
    app.mark_download_finished(node, message.id, download_status)
    app.update_config(True)

    file_size = os.path.getsize(file_name) if file_name else 0

    await upload_telegram_chat(
        client,
        node.upload_user if node.upload_user else client,
        app,
        node,
        message,
        download_status,
        file_name,
    )

    # rclone upload
    if (
        not node.upload_telegram_chat_id
        and download_status is DownloadStatus.SuccessDownload
    ):
        ui_file_name = file_name
        if app.hide_file_name:
            ui_file_name = f"****{os.path.splitext(file_name)[-1]}"
        if await app.upload_file(
            file_name, update_cloud_upload_stat, (node, message.id, ui_file_name)
        ):
            node.upload_success_count += 1

    await report_bot_download_status(
        node.bot,
        node,
        download_status,
        file_size,
    )
    logger.debug(
        "Download task finished: task_id={}, chat_id={}, message_id={}, status={}, "
        "file_size={}, elapsed={:.1f}s",
        node.task_id,
        node.chat_id,
        message.id,
        download_status.name,
        file_size,
        time.time() - task_started_at,
    )


# pylint: disable = R0915,R0914


@record_download_status
async def download_media(
    client: pyrogram.client.Client,
    message: pyrogram.types.Message,
    media_types: List[str],
    file_formats: dict,
    node: TaskNode,
):
    """
    Download media from Telegram.

    Each of the files to download are retried 3 times with a
    delay of 5 seconds each.

    Parameters
    ----------
    client: pyrogram.client.Client
        Client to interact with Telegram APIs.
    message: pyrogram.types.Message
        Message object retrieved from telegram.
    media_types: list
        List of strings of media types to be downloaded.
        Ex : `["audio", "photo"]`
        Supported formats:
            * audio
            * document
            * photo
            * video
            * voice
    file_formats: dict
        Dictionary containing the list of file_formats
        to be downloaded for `audio`, `document` & `video`
        media types.

    Returns
    -------
    int
        Current message id.
    """

    # pylint: disable = R0912

    file_name: str = ""
    ui_file_name: str = ""
    task_start_time: float = time.time()
    media_size = 0
    _media = None
    try:
        message = await fetch_message(client, message)
    except Exception as e:
        request_clash_switch(f"message {getattr(message, 'id', '?')} fetch failed")
        logger.warning(
            "Message[{}]: fetch failed after retries, mark as failed and keep "
            "for recovery: {}",
            getattr(message, "id", "?"),
            e,
        )
        return DownloadStatus.FailedDownload, None

    try:
        for _type in media_types:
            _media = getattr(message, _type, None)
            if _media is None:
                continue
            file_name, temp_file_name, file_format = await _get_media_meta(
                node.chat_id, message, _media, _type
            )
            media_size = getattr(_media, "file_size", 0)

            ui_file_name = file_name
            if app.hide_file_name:
                ui_file_name = f"****{os.path.splitext(file_name)[-1]}"

            if _can_download(_type, file_formats, file_format):
                recovered_status = _recover_existing_download(
                    file_name, temp_file_name, media_size, ui_file_name
                )
                if recovered_status is DownloadStatus.SkipDownload:
                    return DownloadStatus.SkipDownload, None
                if recovered_status is DownloadStatus.SuccessDownload:
                    return DownloadStatus.SuccessDownload, file_name
            else:
                return DownloadStatus.SkipDownload, None

            break
    except Exception as e:
        logger.error(
            f"Message[{message.id}]: "
            f"{_t('could not be downloaded due to following exception')}:\n[{e}].",
            exc_info=True,
        )
        return DownloadStatus.FailedDownload, None
    if _media is None:
        return DownloadStatus.SkipDownload, None

    message_id = message.id
    display_file_name = ui_file_name
    if not app.hide_file_name:
        display_file_name = os.path.basename(file_name)
    logger.bind(console=True).info(
        "开始下载媒体：任务 {}，消息 ID {}，类型 {}，文件 {}",
        node.task_id,
        message_id,
        _type,
        display_file_name,
    )

    for retry in range(DOWNLOAD_RETRY_COUNT):
        try:
            temp_download_path = await _download_media_with_resume(
                client,
                _media,
                temp_file_name,
                media_size,
                update_download_status,
                (
                    message_id,
                    ui_file_name,
                    task_start_time,
                    node,
                    client,
                ),
            )

            if temp_download_path and isinstance(temp_download_path, str):
                _check_download_finish(media_size, temp_download_path, ui_file_name)
                await asyncio.sleep(0.5)
                _move_to_download_path(temp_download_path, file_name)
                # TODO: if not exist file size or media
                return DownloadStatus.SuccessDownload, file_name
        except pyrogram.errors.exceptions.bad_request_400.BadRequest:
            logger.warning(
                f"Message[{message.id}]: {_t('file reference expired, refetching')}..."
            )
        except pyrogram.errors.exceptions.flood_420.FloodWait as wait_err:
            await asyncio.sleep(wait_err.value)
            logger.warning("Message[{}]: FlowWait {}", message.id, wait_err.value)
        except TypeError as e:
            logger.warning(
                f"{_t('Timeout Error occurred when downloading Message')}[{message.id}], "
                f"{_t('retrying after')} {RETRY_TIME_OUT} {_t('seconds')}: {e}"
            )
        except Exception as e:
            logger.warning(
                "Message[{}]: download interrupted on attempt {}/{}: {}",
                message.id,
                retry + 1,
                DOWNLOAD_RETRY_COUNT,
                e,
            )
            if isinstance(e, (TimeoutError, OSError, IOError)) or "stalled" in str(e).lower():
                request_clash_switch(f"message {message.id} download stalled")

        if retry + 1 >= DOWNLOAD_RETRY_COUNT:
            break

        await asyncio.sleep(RETRY_TIME_OUT * (retry + 1))
        try:
            message = await fetch_message(client, message)
        except Exception as e:
            request_clash_switch(f"message {message.id} refetch failed")
            logger.warning(
                "Message[{}]: refetch failed before retry {}/{}: {}",
                message.id,
                retry + 2,
                DOWNLOAD_RETRY_COUNT,
                e,
            )
            continue
        _media = getattr(message, _type, None)
        if _media is None:
            break
        media_size = getattr(_media, "file_size", media_size)

    return DownloadStatus.FailedDownload, None


def _load_config():
    """Load config"""
    app.load_config()


def _check_config() -> bool:
    """Check config"""
    print_meta(logger)
    try:
        _load_config()
        app.prepare_runtime_paths()
        logger.add(
            os.path.join(app.log_file_path, "tdl.log"),
            rotation="10 MB",
            retention="10 days",
            level=app.log_level,
        )
        logger.bind(console=True).info(
            "启动配置读取完成：config={}, data={}, sessions={}（{} 个 session 文件）",
            app.config_file,
            app.app_data_file,
            app.session_file_path,
            app.count_session_files(),
        )
        logger.bind(console=True).info(
            "运行目录准备完成：downloads={}, temp={}, log={}",
            app.save_path,
            app.temp_save_path,
            app.log_file_path,
        )
        set_status_clash_config(app.clash_config)
        logger.info(
            "Runtime paths: base_path={}, config_file={}, app_data_file={}, "
            "save_path={}, temp_path={}, log_path={}, session_path={}",
            app.base_path,
            app.config_file,
            app.app_data_file,
            app.save_path,
            app.temp_save_path,
            app.log_file_path,
            app.session_file_path,
        )
        logger.info(
            "Runtime options: version={}, language={}, bot_enabled={}, "
            "max_download_task={}, max_concurrent_transmissions={}, "
            "download_stall_timeout={}s, history_fetch_timeout={}s, "
            "history_fetch_retries={}, scan_prefetch_limit={}, clash_enabled={}",
            __import__("utils").__version__,
            app.language.name,
            bool(app.bot_token),
            app.max_download_task,
            app.max_concurrent_transmissions,
            app.download_stall_timeout,
            app.history_fetch_timeout,
            app.history_fetch_retries,
            app.scan_prefetch_limit,
            app.clash_config.get("enabled", True),
        )
    except Exception as e:
        logger.exception(f"load config error: {e}")
        return False

    return True


async def worker(client: pyrogram.client.Client):
    """Work for download task"""
    while app.is_running:
        item = None
        try:
            item = await queue.get()
            message = item[0]
            node: TaskNode = item[1]

            if node.is_stop_transmission:
                continue

            logger.debug(
                "Worker picked task: task_id={}, chat_id={}, message_id={}, "
                "queue_size={}",
                node.task_id,
                node.chat_id,
                message.id,
                queue.qsize(),
            )

            if node.client:
                await download_task(node.client, message, node)
            else:
                await download_task(client, message, node)
        except Exception as e:
            logger.exception(f"{e}")
            if item:
                try:
                    message = item[0]
                    node = item[1]
                    node.download_status[message.id] = DownloadStatus.FailedDownload
                    app.set_download_id(
                        node, message.id, DownloadStatus.FailedDownload
                    )
                    app.mark_download_finished(
                        node, message.id, DownloadStatus.FailedDownload
                    )
                    if node.bot:
                        await report_bot_download_status(
                            node.bot, node, DownloadStatus.FailedDownload
                        )
                    app.update_config(True)
                except Exception as update_error:
                    logger.warning("Failed to persist worker failure: {}", update_error)
        finally:
            if item:
                queue.task_done()


async def download_chat_task(
    client: pyrogram.Client,
    chat_download_config: ChatDownloadConfig,
    node: TaskNode,
):
    """Download all task"""
    messages_iter = get_chat_history_v2(
        client,
        node.chat_id,
        limit=node.limit,
        max_id=node.end_offset_id,
        offset_id=chat_download_config.last_read_message_id,
        reverse=True,
        request_timeout=app.history_fetch_timeout,
        retry_count=app.history_fetch_retries,
    )

    chat_download_config.node = node

    if chat_download_config.ids_to_retry:
        logger.info(
            "{}: chat_id={}, pending_ids={}, recover_only={}",
            _t("Downloading files failed during last run"),
            node.chat_id,
            len(chat_download_config.ids_to_retry),
            chat_download_config.recover_only,
        )
        skipped_messages: list = await client.get_messages(  # type: ignore
            chat_id=node.chat_id, message_ids=chat_download_config.ids_to_retry
        )

        for message in skipped_messages:
            await wait_for_scan_prefetch_window(chat_download_config, node)
            await add_download_task(message, node)

    if chat_download_config.recover_only:
        chat_download_config.need_check = True
        chat_download_config.total_task = node.total_task
        node.is_running = True
        logger.info(
            "Recovery-only task queued: task_id={}, chat_id={}, total_task={}",
            node.task_id,
            node.chat_id,
            node.total_task,
        )
        return

    queued_before_history = node.total_task
    try:
        async for message in messages_iter:  # type: ignore
            meta_data = MetaData()

            caption = message.caption
            if caption:
                caption = validate_title(caption)
                app.set_caption_name(node.chat_id, message.media_group_id, caption)
                app.set_caption_entities(
                    node.chat_id, message.media_group_id, message.caption_entities
                )
            else:
                caption = app.get_caption_name(node.chat_id, message.media_group_id)
            set_meta_data(meta_data, message, caption)

            if app.need_skip_message(chat_download_config, message.id):
                continue

            if app.exec_filter(chat_download_config, meta_data):
                await wait_for_scan_prefetch_window(chat_download_config, node)
                await add_download_task(message, node)
            else:
                node.download_status[message.id] = DownloadStatus.SkipDownload
                if message.media_group_id:
                    await upload_telegram_chat(
                        client,
                        node.upload_user,
                        app,
                        node,
                        message,
                        DownloadStatus.SkipDownload,
                    )
    except Exception as exc:
        request_clash_switch(
            f"chat history failed: chat_id={node.chat_id}, "
            f"last_read_message_id={chat_download_config.last_read_message_id}"
        )
        chat_download_config.need_check = True
        node.is_running = False
        logger.exception(
            "Read chat history failed: task_id={}, chat_id={}, "
            "last_read_message_id={}, error={}",
            node.task_id,
            node.chat_id,
            chat_download_config.last_read_message_id,
            exc,
        )
        return

    chat_download_config.need_check = True
    chat_download_config.total_task = node.total_task
    node.is_running = True
    if node.total_task == queued_before_history:
        logger.info(
            "No new downloadable messages found: task_id={}, chat_id={}, "
            "last_read_message_id={}",
            node.task_id,
            node.chat_id,
            chat_download_config.last_read_message_id,
        )
    else:
        logger.info(
            "Chat history queued: task_id={}, chat_id={}, queued={}",
            node.task_id,
            node.chat_id,
            node.total_task - queued_before_history,
        )


async def download_all_chat(client: pyrogram.Client):
    """Download All chat"""
    if app.chat_download_config:
        logger.bind(console=True).info(
            "检测到 {} 个 config/恢复下载任务，开始扫描消息并加入下载队列。",
            len(app.chat_download_config),
        )
    else:
        logger.bind(console=True).info("config.yaml 未配置会话下载任务，等待机器人命令。")

    for key, value in app.chat_download_config.items():
        if value.recover_only and not value.ids_to_retry:
            logger.info("Skip empty recovered bot task: chat_id={}", key)
            value.need_check = True
            continue

        retry_count = len(value.ids_to_retry)
        continue_from_id = min(value.ids_to_retry) if value.ids_to_retry else (
            value.last_read_message_id or value.start_offset_id
        )
        task_source = "机器人" if value.is_bot_task else "config"
        task_kind = "异常中断恢复" if value.recover_only or retry_count else "启动"
        range_text = (
            f"{value.start_offset_id}-{value.end_offset_id or '最新'}"
            if value.start_offset_id or value.end_offset_id
            else "未指定"
        )
        logger.bind(console=True).info(
            "收到{}{}下载任务：chat_id={}，从消息 ID {} 继续，"
            "待恢复 ID {} 个，原范围 {}。",
            task_source,
            task_kind,
            key,
            continue_from_id or 0,
            retry_count,
            range_text,
        )

        if app.bot_token:
            reply_message = (
                f"恢复机器人下载任务: {key}"
                if value.is_bot_task
                else f"config.yaml 会话下载任务: {key}"
            )
            value.node = await get_download_bot().create_status_node(
                key,
                value,
                reply_message,
                value.bot_from_user_id,
            )
        else:
            value.node = TaskNode(
                chat_id=key,
                limit=value.limit,
                start_offset_id=value.start_offset_id,
                end_offset_id=value.end_offset_id,
                download_filter=value.download_filter,
            )
        try:
            logger.info(
                "Start chat download task: task_id={}, chat_id={}, recover_only={}, "
                "pending_ids={}",
                value.node.task_id,
                key,
                value.recover_only,
                len(value.ids_to_retry),
            )
            logger.bind(console=True).info(
                "开始下载任务 {}：chat_id={}，正在扫描消息并边扫描边下载。",
                value.node.task_id,
                key,
            )
            await download_chat_task(client, value, value.node)
        except Exception as e:
            logger.exception("Download {} error: {}", key, e)
        finally:
            value.need_check = True


async def run_until_all_task_finish():
    """Normal download"""
    while True:
        finish: bool = True
        for _, value in app.chat_download_config.items():
            if not value.need_check or value.total_task != value.finish_task:
                finish = False

        if (not app.bot_token and finish) or app.restart_program:
            break

        await asyncio.sleep(1)


async def _switch_clash_node():
    """Switch Clash to a tested US node in a worker thread."""
    controller = ClashController(app.clash_config)
    return await asyncio.to_thread(controller.switch_to_fast_us_node)


async def monitor_low_download_speed():
    """Switch Clash node when downloads are slow or Telegram requests fail."""
    global _clash_switch_reason
    config = app.clash_config
    if not config.get("enabled", True):
        return

    low_speed_bytes = int(config.get("low_speed_kb", 100)) * 1024
    low_speed_seconds = int(config.get("low_speed_seconds", 60))
    cooldown_seconds = int(config.get("switch_cooldown_seconds", 300))
    low_speed_since = None
    last_switch_time = 0

    while app.is_running:
        await asyncio.sleep(LOW_SPEED_MONITOR_INTERVAL)

        now = time.time()
        switch_reason = None

        if _clash_switch_event.is_set():
            switch_reason = _clash_switch_reason or "Telegram network request failed"
            healthy, active_count, speed, threshold = _downloads_are_healthy_for_clash_switch()
            if healthy:
                _clash_switch_event.clear()
                _clash_switch_reason = None
                low_speed_since = None
                logger.warning(
                    "Skipped Clash switch because active downloads recovered: reason={}, active={}, speed={}/s, threshold={}/s",
                    switch_reason,
                    active_count,
                    format_byte(speed),
                    format_byte(threshold),
                )
                continue
        elif get_active_download_count() <= 0:
            low_speed_since = None
            continue
        else:
            speed = get_total_download_speed()
            if speed >= low_speed_bytes:
                low_speed_since = None
                continue

            if low_speed_since is None:
                low_speed_since = now
                continue

            if now - low_speed_since < low_speed_seconds:
                continue

            switch_reason = (
                f"download speed stayed below {int(low_speed_bytes / 1024)} KB/s "
                f"for {low_speed_seconds} seconds"
            )

        if now - last_switch_time < cooldown_seconds:
            continue

        _clash_switch_event.clear()
        _clash_switch_reason = None

        logger.warning("{}; testing Clash nodes", switch_reason)

        try:
            result = await _switch_clash_node()
        except Exception as exc:
            logger.warning("Clash auto switch failed: {}", exc)
            low_speed_since = None
            last_switch_time = now
            continue

        if result:
            bump_network_epoch()
            logger.warning(
                "Switched Clash selector {} to {} ({} ms); active downloads will retry",
                result.selector,
                result.node,
                result.delay,
            )
        else:
            logger.warning("Clash auto switch found no usable US node")

        low_speed_since = None
        last_switch_time = now


async def log_download_heartbeat():
    """Write periodic heartbeat so long downloads never look silent."""
    while app.is_running:
        await asyncio.sleep(DOWNLOAD_HEARTBEAT_INTERVAL)
        active_count = get_active_download_count()
        queue_size = queue.qsize()
        if active_count <= 0 and queue_size <= 0:
            continue

        logger.info(
            "Download heartbeat: active={}, queue={}, speed={}/s",
            active_count,
            queue_size,
            format_byte(get_total_download_speed()),
        )


def _exec_loop():
    """Exec loop"""

    app.loop.run_until_complete(run_until_all_task_finish())


async def start_server(client: pyrogram.Client):
    """
    Start the server using the provided client.
    """
    await client.start()


async def stop_server(client: pyrogram.Client):
    """
    Stop the server using the provided client.
    """
    await client.stop()


def main():
    """Main function of the downloader."""
    asyncio.set_event_loop(app.loop)
    tasks = []
    client = HookClient(
        "media_downloader",
        api_id=app.api_id,
        api_hash=app.api_hash,
        proxy=app.proxy,
        workdir=app.session_file_path,
        start_timeout=app.start_timeout,
        no_updates=True,
    )
    try:
        app.pre_run()
        init_web(app)

        set_max_concurrent_transmissions(client, app.max_concurrent_transmissions)

        app.loop.run_until_complete(start_server(client))
        logger.success(_t("Successfully started (Press Ctrl+C to stop)"))

        if app.bot_token:
            app.loop.run_until_complete(
                start_download_bot(app, client, add_download_task, download_chat_task)
            )
            logger.bind(console=True).success("机器人已启动，等待命令。")

        app.loop.create_task(download_all_chat(client))
        logger.bind(console=True).success("软件启动完成，下载工作线程已就绪。")
        tasks.append(app.loop.create_task(monitor_low_download_speed()))
        tasks.append(app.loop.create_task(log_download_heartbeat()))
        for _ in range(app.max_download_task):
            task = app.loop.create_task(worker(client))
            tasks.append(task)
        _exec_loop()
    except KeyboardInterrupt:
        logger.info(_t("KeyboardInterrupt"))
    except Exception as e:
        logger.exception("{}", e)
    finally:
        app.is_running = False
        if app.bot_token:
            app.loop.run_until_complete(stop_download_bot())
        app.loop.run_until_complete(stop_server(client))
        for task in tasks:
            task.cancel()
        logger.info(_t("Stopped!"))
        # check_for_updates(app.proxy)
        logger.info(f"{_t('update config')}......")
        app.update_config()
        logger.success(
            f"{_t('Updated last read message_id to config file')},"
            f"{_t('total download')} {app.total_download_task}, "
            f"{_t('total upload file')} "
            f"{app.cloud_drive_config.total_upload_success_file_count}"
        )


if __name__ == "__main__":
    if _check_config():
        main()
