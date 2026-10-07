"""Desktop shell integration.

The Tauri desktop app starts the engine with ``TDL_DESKTOP=1`` and a random
``TDL_DESKTOP_TOKEN``.  In that mode the engine:

* exposes a small token-protected JSON API on the existing Flask server,
* keeps running after all configured chats finish so new tasks can be added,
* appends every finished download to a monthly JSONL history file that the
  desktop dashboard aggregates.
"""

import asyncio
import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional, Union

from flask import Flask, abort, jsonify, request
from loguru import logger

import utils
from module.app import (
    Application,
    ChatDownloadConfig,
    DownloadStatus,
    TaskNode,
    TaskType,
)
from module.bot import get_download_bot
from module.download_stat import (
    DownloadState,
    get_download_result_snapshot,
    get_download_state,
    get_total_download_speed,
    set_download_state,
)
from module.network_watchdog import get_last_route_switch, is_waiting_for_network
from module.pyrogram_extension import parse_link
from utils.format import replace_date_time

DESKTOP_ENV = "TDL_DESKTOP"
TOKEN_ENV = "TDL_DESKTOP_TOKEN"
TOKEN_HEADER = "X-TDL-Token"
HISTORY_DIR_NAME = "stats"
RECENT_TASK_LIMIT = 20
RECENT_DOWNLOAD_LIMIT = 30
TASK_REAP_INTERVAL = 5
API_CALL_TIMEOUT = 60
# Suffix on persisted commands of tasks created from the desktop app.
DESKTOP_COMMAND_MARK = "(desktop)"

_STATUS_NAMES = {
    DownloadStatus.SuccessDownload: "success",
    DownloadStatus.SkipDownload: "skipped",
    DownloadStatus.FailedDownload: "failed",
}


def is_desktop_mode() -> bool:
    """Return whether the engine was launched by the desktop shell."""
    return os.environ.get(DESKTOP_ENV) == "1"


def configure_desktop_stdio():
    """Use line-buffered UTF-8 pipes so the shell sees logs and prompts promptly."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (ValueError, OSError):
            pass
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _chat_display_name(chat, fallback) -> str:
    """Best-effort human readable chat name."""
    if chat is None:
        return str(fallback)
    for attr in ("title", "first_name", "username"):
        value = getattr(chat, attr, None)
        if value:
            return str(value)
    return str(fallback)


class DownloadHistory:
    """Append-only download history, one JSON object per line and month."""

    def __init__(self, base_path: str, enabled: bool = True):
        self.directory = os.path.join(base_path, HISTORY_DIR_NAME)
        self.enabled = enabled
        self._lock = threading.Lock()
        self.counters: Dict[str, int] = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "bytes": 0,
        }
        self.recent: Deque[dict] = deque(maxlen=RECENT_DOWNLOAD_LIMIT)

    def file_path(self, when: Optional[datetime] = None) -> str:
        """History file for the month containing ``when``."""
        when = when or datetime.now()
        return os.path.join(self.directory, f"history-{when:%Y-%m}.jsonl")

    # pylint: disable = R0913
    def record(
        self,
        node: TaskNode,
        message,
        status: DownloadStatus,
        file_name: Optional[str],
        file_size: int,
        started_at: float,
        hide_file_name: bool = False,
    ) -> Optional[dict]:
        """Record one finished media download; never raises."""
        status_name = _STATUS_NAMES.get(status)
        if status_name is None:
            # ``Downloading`` means a duplicate request for an in-flight item.
            return None

        media = getattr(message, "media", None)
        media_type = getattr(media, "value", None) or ("text" if file_name else "")
        chat = getattr(message, "chat", None)
        shown_name = file_name or ""
        if hide_file_name and shown_name:
            shown_name = f"****{os.path.splitext(shown_name)[-1]}"

        entry = {
            "ts": int(time.time()),
            "task": node.task_id,
            "chat_id": str(node.chat_id),
            "chat": _chat_display_name(chat, node.chat_id),
            "msg": getattr(message, "id", 0),
            "type": media_type,
            "status": status_name,
            "size": int(file_size or 0),
            "file": shown_name,
            "elapsed": round(max(time.time() - started_at, 0.0), 1),
        }

        with self._lock:
            self.counters[status_name] += 1
            if status_name == "success":
                self.counters["bytes"] += entry["size"]
            self.recent.appendleft(entry)

            if not self.enabled:
                return entry
            try:
                os.makedirs(self.directory, exist_ok=True)
                with open(self.file_path(), "a", encoding="utf-8") as history_file:
                    history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.warning("Failed to write download history: {}", exc)
        return entry


class DesktopApiError(Exception):
    """User-facing API error."""


class DesktopRuntime:
    """Runtime view of the engine for the desktop shell."""

    # pylint: disable = R0913
    def __init__(
        self,
        app: Application,
        history: DownloadHistory,
        queue_size: Callable[[], int],
        download_chat_task: Callable,
    ):
        self.app = app
        self.history = history
        self.queue_size = queue_size
        self.download_chat_task = download_chat_task
        self.client = None
        self.ready = False
        self.started_at = time.time()
        self.chat_titles: Dict[str, str] = {}
        self._task_lock = threading.Lock()
        self._last_tasks: Dict[str, dict] = {}
        self._recent_tasks: Deque[dict] = deque(maxlen=RECENT_TASK_LIMIT)

    # ------------------------------------------------------------------ tasks
    def _collect_nodes(self) -> List[TaskNode]:
        nodes: Dict[int, TaskNode] = {}
        for node in list(get_download_bot().task_node.values()):
            nodes[id(node)] = node
        for chat_config in list(self.app.chat_download_config.values()):
            node = chat_config.node
            if node is not None and node.chat_id:
                nodes[id(node)] = node
        return list(nodes.values())

    @staticmethod
    def task_key(node: TaskNode) -> str:
        """Stable key; config tasks without a bot share task id 0."""
        return str(node.task_id) if node.task_id else f"chat:{node.chat_id}"

    def _summarize(self, node: TaskNode) -> dict:
        chat_config = self.app.chat_download_config.get(node.chat_id)
        if chat_config is not None and chat_config.node is not node:
            chat_config = None
        if node.bot:
            source = "bot"
        elif chat_config is not None and chat_config.is_bot_task:
            command = str(chat_config.bot_command_message or "")
            source = "desktop" if command.endswith(DESKTOP_COMMAND_MARK) else "recovery"
        else:
            source = "config"

        summary = {
            "key": self.task_key(node),
            "task_id": node.task_id,
            "chat_id": str(node.chat_id),
            "chat": self.chat_titles.get(str(node.chat_id), str(node.chat_id)),
            "type": node.task_type.name.lower(),
            "source": source,
            "running": bool(node.is_running),
            "scan_finished": bool(node.scan_finished),
            "stopped": bool(node.is_stop_transmission),
            "finished": bool(node.is_finish()),
            "total": node.total_task,
            "done": node.total_download_task,
            "success": node.success_download_task,
            "failed": node.failed_download_task,
            "skipped": node.skip_download_task,
            "bytes": node.total_download_byte,
            "start_id": node.start_offset_id,
            "end_id": node.end_offset_id,
            "filter": str(node.download_filter or ""),
            "pending": len(chat_config.ids_to_retry) if chat_config else 0,
            "last_read_message_id": (
                chat_config.last_read_message_id if chat_config else 0
            ),
        }
        if node.task_type is not TaskType.Download:
            summary.update(
                {
                    "total": node.total_forward_task,
                    "done": node.success_forward_task
                    + node.failed_forward_task
                    + node.skip_forward_task,
                    "success": node.success_forward_task,
                    "failed": node.failed_forward_task,
                    "skipped": node.skip_forward_task,
                }
            )
        return summary

    def task_snapshot(self) -> dict:
        """Current tasks plus tasks that finished since the shell last looked."""
        current = {}
        for node in self._collect_nodes():
            summary = self._summarize(node)
            current[summary["key"]] = summary

        with self._task_lock:
            for key, summary in self._last_tasks.items():
                if key not in current:
                    summary = dict(summary, finished=True, running=False)
                    summary["ended_at"] = int(time.time())
                    self._recent_tasks.appendleft(summary)
            self._last_tasks = current
            recent = list(self._recent_tasks)

        return {"active": list(current.values()), "recent": recent}

    def stop_task(self, key: str) -> bool:
        """Stop a task by key; bot/desktop tasks are also forgotten."""
        bot = get_download_bot()
        if key.isdigit() and int(key) in bot.task_node:
            bot.stop_task(key)
            return True
        for node in self._collect_nodes():
            if self.task_key(node) == key:
                node.stop_transmission()
                self.app.forget_bot_download_task(node)
                return True
        return False

    def _find_active_node(self, chat_id) -> Optional[TaskNode]:
        for node in self._collect_nodes():
            if (
                str(node.chat_id) == str(chat_id)
                and node.task_type is TaskType.Download
                and not node.is_finish()
            ):
                return node
        return None

    async def create_task(
        self,
        link: str,
        start_id: int = 0,
        end_id: int = 0,
        download_filter: str = "",
    ) -> dict:
        """Create a download task, mirroring the bot's /download command."""
        if self.client is None or not self.ready:
            raise DesktopApiError("引擎尚未完成登录，暂时无法创建任务")

        link = (link or "").strip()
        if not link:
            raise DesktopApiError("请输入频道、群组或消息链接")

        bot = get_download_bot()
        if bot.app is None:
            bot.app = self.app

        chat_ref, message_id, _ = await parse_link(self.client, link)
        if not chat_ref:
            raise DesktopApiError("无法解析链接，请使用 https://t.me/... 形式的链接")
        entity = await self.client.get_chat(chat_ref)
        chat_id = entity.id
        title = _chat_display_name(entity, chat_id)
        self.chat_titles[str(chat_id)] = title

        active = self._find_active_node(chat_id)
        if active is not None:
            raise DesktopApiError(f"该会话已有进行中的任务 #{active.task_id}")

        if message_id and not start_id and not end_id:
            start_id = end_id = message_id
        if end_id and end_id < start_id:
            raise DesktopApiError("结束消息 ID 不能小于起始消息 ID")

        download_filter = (download_filter or "").strip()
        if download_filter:
            download_filter = replace_date_time(download_filter)
            valid, error = bot.filter.check_filter(download_filter)
            if not valid:
                raise DesktopApiError(f"过滤表达式无效：{error}")

        limit = end_id - start_id + 1 if end_id else 0
        command = f"/download {link} {start_id} {end_id}"
        if download_filter:
            command += f" {download_filter}"

        chat_config = ChatDownloadConfig()
        chat_config.is_bot_task = True
        chat_config.recover_only = False
        chat_config.last_read_message_id = start_id
        chat_config.download_filter = download_filter or None
        chat_config.limit = limit
        chat_config.start_offset_id = start_id
        chat_config.end_offset_id = end_id
        # The link is what restores the channel peer after a restart.
        chat_config.bot_command_message = f"{command} {DESKTOP_COMMAND_MARK}"
        self.app.chat_download_config[chat_id] = chat_config

        reply_message = (
            f"桌面端任务：来自 {title} 下载消息 ID = {start_id} - {end_id or '最新'}"
        )
        node = await bot.create_status_node(chat_id, chat_config, reply_message)
        node.chat_title = title
        self.app.update_config(True)
        logger.bind(console=True).info(
            "收到桌面端下载任务：chat_id={}，消息范围 {}-{}。",
            chat_id,
            start_id,
            end_id or "最新",
        )
        self.app.loop.create_task(
            self.download_chat_task(self.client, chat_config, node)
        )
        return {"task_id": node.task_id, "chat_id": str(chat_id), "chat": title}

    async def reap_finished_tasks(self):
        """Forget finished tasks when no bot loop is doing it."""
        bot = get_download_bot()
        while self.app.is_running:
            await asyncio.sleep(TASK_REAP_INTERVAL)
            if bot.bot is not None:
                continue
            for key, node in list(bot.task_node.items()):
                if node.is_running and node.is_finish():
                    self.app.forget_bot_download_task(node)
                    bot.remove_task_node(key)

    # ----------------------------------------------------------------- status
    def status(self) -> dict:
        """Full status document for the dashboard."""
        downloads = []
        for chat_id, messages in get_download_result_snapshot().items():
            for message_id, value in messages.items():
                if value.get("terminal", False):
                    continue
                total = value.get("total_size") or 0
                done = value.get("down_byte") or 0
                downloads.append(
                    {
                        "chat_id": str(chat_id),
                        "chat": self.chat_titles.get(str(chat_id), str(chat_id)),
                        "message_id": message_id,
                        "task_id": value.get("task_id", 0),
                        "file": os.path.basename(value.get("file_name", "")),
                        "total": total,
                        "done": done,
                        "speed": int(value.get("download_speed") or 0),
                        "progress": round(done / total * 100, 1) if total else 0,
                        "started_at": int(value.get("start_time") or 0),
                    }
                )
        downloads.sort(key=lambda item: item["started_at"])

        pending = []
        for chat_id, chat_config in list(self.app.chat_download_config.items()):
            if chat_config.ids_to_retry:
                pending.append(
                    {
                        "chat_id": str(chat_id),
                        "chat": self.chat_titles.get(str(chat_id), str(chat_id)),
                        "count": len(chat_config.ids_to_retry),
                    }
                )

        bot = get_download_bot()
        route_switch = get_last_route_switch()
        return {
            "version": utils.__version__,
            "pid": os.getpid(),
            "ready": self.ready,
            "uptime": int(time.time() - self.started_at),
            "paused": get_download_state() is DownloadState.StopDownload,
            "offline": is_waiting_for_network(),
            "speed": get_total_download_speed(),
            "queue": self.queue_size(),
            "active_count": len(downloads),
            "downloads": downloads,
            "tasks": self.task_snapshot(),
            "pending": pending,
            "session": dict(self.history.counters),
            "recent": list(self.history.recent),
            "bot": {"enabled": bool(self.app.bot_token), "running": bot.bot is not None},
            "clash": {
                "enabled": bool(self.app.clash_config.get("enabled", True)),
                "last_switch": route_switch,
            },
            "save_path": self.app.save_path,
            "max_download_task": self.app.max_download_task,
        }

    def remember_chat_title(self, chat_id: Union[int, str], message) -> None:
        """Cache a chat title from a message for task/downloads display."""
        chat = getattr(message, "chat", None)
        if chat is not None:
            self.chat_titles[str(chat_id)] = _chat_display_name(chat, chat_id)

    def run_coroutine(self, coro):
        """Run a coroutine on the engine loop from a Flask worker thread."""
        future = asyncio.run_coroutine_threadsafe(coro, self.app.loop)
        return future.result(timeout=API_CALL_TIMEOUT)


def register_desktop_api(flask_app: Flask, runtime: DesktopRuntime, token: str):
    """Register ``/api/desktop`` routes guarded by the per-launch token."""

    def check_token():
        if not token or request.headers.get(TOKEN_HEADER) != token:
            abort(401)

    def error(message: str, code: int = 400):
        return jsonify({"ok": False, "error": message}), code

    @flask_app.route("/api/desktop/status")
    def desktop_status():
        check_token()
        return jsonify(runtime.status())

    @flask_app.route("/api/desktop/pause", methods=["POST"])
    def desktop_pause():
        check_token()
        set_download_state(DownloadState.StopDownload)
        return jsonify({"ok": True, "paused": True})

    @flask_app.route("/api/desktop/resume", methods=["POST"])
    def desktop_resume():
        check_token()
        set_download_state(DownloadState.Downloading)
        return jsonify({"ok": True, "paused": False})

    @flask_app.route("/api/desktop/tasks", methods=["POST"])
    def desktop_create_task():
        check_token()
        body = request.get_json(silent=True) or {}
        try:
            result = runtime.run_coroutine(
                runtime.create_task(
                    str(body.get("link", "")),
                    int(body.get("start_id") or 0),
                    int(body.get("end_id") or 0),
                    str(body.get("filter") or ""),
                )
            )
        except DesktopApiError as exc:
            return error(str(exc))
        except (TypeError, ValueError) as exc:
            return error(f"参数错误：{exc}")
        except Exception as exc:  # pylint: disable = W0718
            logger.exception("Desktop task creation failed: {}", exc)
            return error(f"创建任务失败：{exc}", 500)
        return jsonify({"ok": True, **result})

    @flask_app.route("/api/desktop/tasks/<key>/stop", methods=["POST"])
    def desktop_stop_task(key: str):
        check_token()
        if not runtime.stop_task(key):
            return error("任务不存在或已结束", 404)
        return jsonify({"ok": True})

    @flask_app.route("/api/desktop/filter/check", methods=["POST"])
    def desktop_check_filter():
        check_token()
        body = request.get_json(silent=True) or {}
        expression = replace_date_time(str(body.get("filter") or ""))
        valid, message = get_download_bot().filter.check_filter(expression)
        return jsonify({"ok": True, "valid": valid, "error": message})

    @flask_app.route("/api/desktop/shutdown", methods=["POST"])
    def desktop_shutdown():
        check_token()
        logger.bind(console=True).info("收到桌面端退出请求，正在保存状态并停止引擎。")
        runtime.app.shutdown_requested = True
        return jsonify({"ok": True})
