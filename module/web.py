"""web ui for media download"""

import copy
import logging
import os
import threading
import time

from flask import Flask, jsonify, render_template, request
from flask_login import LoginManager, UserMixin, login_required, login_user

import utils
from module.app import Application, DownloadStatus, TaskNode
from module.download_stat import (
    DownloadState,
    get_active_download_count,
    get_download_result,
    get_download_state,
    get_total_download_speed,
    set_download_state,
)
from module.language import Language
from utils.crypto import AesBase64
from utils.format import format_byte

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

_flask_app = Flask(__name__)

_flask_app.secret_key = "tdl"
_login_manager = LoginManager()
_login_manager.login_view = "login"
_login_manager.init_app(_flask_app)
web_login_users: dict = {}
deAesCrypt = AesBase64("1234123412ABCDEF", "ABCDEF1234123412")
_runtime_app: Application | None = None


class User(UserMixin):
    """Web Login User"""

    def __init__(self):
        self.sid = "root"

    @property
    def id(self):
        """ID"""
        return self.sid


@_login_manager.user_loader
def load_user(_):
    """
    Load a user object from the user ID.

    Returns:
        User: The user object.
    """
    return User()


def get_flask_app() -> Flask:
    """get flask app instance"""
    return _flask_app


def run_web_server(app: Application):
    """
    Runs a web server using the Flask framework.
    """

    get_flask_app().run(
        app.web_host, app.web_port, debug=app.debug_web, use_reloader=False
    )


# pylint: disable = W0603
def init_web(app: Application):
    """
    Set the value of the users variable.

    Args:
        users: The list of users to set.

    Returns:
        None.
    """
    global web_login_users
    global _runtime_app
    _runtime_app = app
    if app.web_login_secret:
        web_login_users = {"root": app.web_login_secret}
    else:
        _flask_app.config["LOGIN_DISABLED"] = True
    if app.debug_web:
        threading.Thread(target=run_web_server, args=(app,)).start()
    else:
        threading.Thread(
            target=get_flask_app().run, daemon=True, args=(app.web_host, app.web_port)
        ).start()


def _get_runtime_app() -> Application:
    if _runtime_app is None:
        raise RuntimeError("Web runtime app is not initialized")
    return _runtime_app


def _download_items(already_down: bool | None = None) -> list[dict]:
    items = []
    for chat_id, messages in get_download_result().items():
        for message_id, value in messages.items():
            total_size = int(value.get("total_size") or 0)
            down_byte = int(value.get("down_byte") or 0)
            is_done = total_size > 0 and down_byte >= total_size

            if already_down is True and not is_done:
                continue
            if already_down is False and is_done:
                continue

            progress = round(down_byte / total_size * 100, 1) if total_size else 0
            started_at = float(value.get("start_time") or 0)
            updated_at = float(value.get("end_time") or 0)
            items.append(
                {
                    "chat": str(chat_id),
                    "id": str(message_id),
                    "task_id": value.get("task_id", ""),
                    "filename": os.path.basename(value.get("file_name", "")),
                    "save_path": str(value.get("file_name", "")).replace("\\", "/"),
                    "total_size": format_byte(total_size),
                    "total_size_bytes": total_size,
                    "down_size": format_byte(down_byte),
                    "down_size_bytes": down_byte,
                    "download_progress": progress,
                    "download_speed": f"{format_byte(value.get('download_speed', 0))}/s",
                    "status": "done" if is_done else "downloading",
                    "started_at": started_at,
                    "updated_at": updated_at,
                    "elapsed_seconds": round(max(time.time() - started_at, 0), 1)
                    if started_at
                    else 0,
                }
            )
    return sorted(
        items,
        key=lambda item: (item["status"] == "done", item["chat"], int(item["id"] or 0)),
    )


def _status_count(status_map: dict, status: DownloadStatus) -> int:
    return sum(1 for value in status_map.values() if value is status)


def _serialize_task_node(node: TaskNode | None) -> dict:
    if node is None:
        return {}

    return {
        "task_id": node.task_id,
        "chat_id": str(node.chat_id),
        "type": node.task_type.name,
        "running": node.is_running,
        "stopped": node.is_stop_transmission,
        "total": node.total_task,
        "finished": node.total_download_task,
        "success": node.success_download_task
        or _status_count(node.download_status, DownloadStatus.SuccessDownload),
        "failed": node.failed_download_task
        or _status_count(node.download_status, DownloadStatus.FailedDownload),
        "skipped": node.skip_download_task
        or _status_count(node.download_status, DownloadStatus.SkipDownload),
        "last_bot_message": node.last_edit_msg,
        "from_user_id": str(node.from_user_id or ""),
        "reply_message_id": node.reply_message_id,
        "range": {
            "start_offset_id": node.start_offset_id,
            "end_offset_id": node.end_offset_id,
            "limit": node.limit,
        },
    }


def _runtime_tasks(app: Application) -> list[dict]:
    tasks = []
    seen_task_ids = set()
    for chat_id, config in app.chat_download_config.items():
        node = getattr(config, "node", None)
        item = _serialize_task_node(node)
        item.update(
            {
                "chat_id": str(chat_id),
                "source": "bot" if getattr(config, "is_bot_task", False) else "config",
                "recover_only": getattr(config, "recover_only", False),
                "need_check": getattr(config, "need_check", False),
                "pending_retry": len(getattr(config, "ids_to_retry", []) or []),
                "last_read_message_id": getattr(config, "last_read_message_id", 0),
                "finish_task": getattr(config, "finish_task", 0),
                "total_task": getattr(config, "total_task", 0),
            }
        )
        if item.get("task_id"):
            seen_task_ids.add(item["task_id"])
        tasks.append(item)

    try:
        from module.bot import get_download_bot

        bot = get_download_bot()
        for task_id, node in bot.task_node.items():
            if task_id in seen_task_ids:
                continue
            item = _serialize_task_node(node)
            item["source"] = "bot"
            item["pending_retry"] = 0
            tasks.append(item)
    except Exception:
        pass

    return tasks


def _public_config(app: Application) -> dict:
    return {
        "language": app.language.name,
        "save_path": app.save_path,
        "web_host": app.web_host,
        "web_port": app.web_port,
        "max_download_task": app.max_download_task,
        "max_concurrent_transmissions": app.max_concurrent_transmissions,
        "scan_prefetch_limit": app.scan_prefetch_limit,
        "download_stall_timeout": app.download_stall_timeout,
        "history_fetch_timeout": app.history_fetch_timeout,
        "history_fetch_retries": app.history_fetch_retries,
        "start_timeout": app.start_timeout,
        "log_level": app.log_level,
        "hide_file_name": app.hide_file_name,
        "enable_download_txt": app.enable_download_txt,
        "drop_no_audio_video": app.drop_no_audio_video,
        "media_types": list(app.media_types),
        "file_formats": copy.deepcopy(app.file_formats),
        "chat": copy.deepcopy(app.config.get("chat", [])),
        "clash": copy.deepcopy(app.clash_config),
    }


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def _int_value(data: dict, key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(int(data.get(key, default)), minimum)
    except (TypeError, ValueError):
        return default


def _save_public_config(app: Application, data: dict) -> list[str]:
    restart_required = []
    config = app.config

    if "language" in data:
        language = str(data.get("language") or app.language.name).upper()
        if language in Language.__members__:
            app.set_language(Language[language])
            config["language"] = app.language.name

    string_fields = ("save_path", "web_host", "log_level")
    for key in string_fields:
        if key in data:
            value = str(data.get(key) or "")
            setattr(app, key, value)
            config[key] = value

    int_fields = {
        "web_port": 1,
        "max_download_task": 1,
        "max_concurrent_transmissions": 1,
        "scan_prefetch_limit": 0,
        "download_stall_timeout": 1,
        "history_fetch_timeout": 1,
        "history_fetch_retries": 1,
        "start_timeout": 1,
    }
    for key, minimum in int_fields.items():
        if key in data:
            value = _int_value(data, key, getattr(app, key), minimum)
            if key in ("max_download_task", "web_host", "web_port"):
                restart_required.append(key)
            setattr(app, key, value)
            config[key] = value

    for key in ("hide_file_name", "enable_download_txt", "drop_no_audio_video"):
        if key in data:
            value = _bool_value(data.get(key))
            setattr(app, key, value)
            config[key] = value

    if isinstance(data.get("media_types"), list):
        app.media_types = [str(item) for item in data["media_types"] if item]
        config["media_types"] = list(app.media_types)

    if isinstance(data.get("file_formats"), dict):
        app.file_formats = data["file_formats"]
        config["file_formats"] = copy.deepcopy(app.file_formats)

    if isinstance(data.get("chat"), list):
        config["chat"] = data["chat"]

    if isinstance(data.get("clash"), dict):
        app.clash_config.update(data["clash"])
        config["clash"] = copy.deepcopy(app.clash_config)

    app.update_config(True)
    return sorted(set(restart_required))


@_flask_app.route("/login", methods=["GET", "POST"])
def login():
    """
    Function to handle the login route.

    Parameters:
    - No parameters

    Returns:
    - If the request method is "POST" and the username and
      password match the ones in the web_login_users dictionary,
      it returns a JSON response with a code of "1".
    - Otherwise, it returns a JSON response with a code of "0".
    - If the request method is not "POST", it returns the rendered "login.html" template.
    """
    if request.method == "POST":
        username = "root"
        web_login_form = {}
        for key, value in request.form.items():
            if value:
                value = deAesCrypt.decrypt(value)
            web_login_form[key] = value

        if not web_login_form.get("password"):
            return jsonify({"code": "0"})

        password = web_login_form["password"]
        if username in web_login_users and web_login_users[username] == password:
            user = User()
            login_user(user)
            return jsonify({"code": "1"})

        return jsonify({"code": "0"})

    return render_template("login.html")


@_flask_app.route("/")
@login_required
def index():
    """Index html"""
    return render_template(
        "index.html",
        download_state=(
            "pause" if get_download_state() is DownloadState.Downloading else "continue"
        ),
    )


@_flask_app.route("/get_download_status")
@login_required
def get_download_speed():
    """Get download speed"""
    return (
        '{ "download_speed" : "'
        + format_byte(get_total_download_speed())
        + '/s" , "upload_speed" : "0.00 B/s" } '
    )


@_flask_app.route("/set_download_state", methods=["POST"])
@login_required
def web_set_download_state():
    """Set download state"""
    state = request.args.get("state")

    if state == "continue" and get_download_state() is DownloadState.StopDownload:
        set_download_state(DownloadState.Downloading)
        return "pause"

    if state == "pause" and get_download_state() is DownloadState.Downloading:
        set_download_state(DownloadState.StopDownload)
        return "continue"

    return state


@_flask_app.route("/api/dashboard")
@login_required
def api_dashboard():
    """Return realtime dashboard data for the modern web UI."""
    app = _get_runtime_app()
    downloads = _download_items()
    active_downloads = [item for item in downloads if item["status"] != "done"]
    completed_downloads = [item for item in downloads if item["status"] == "done"]
    tasks = _runtime_tasks(app)

    return jsonify(
        {
            "version": utils.__version__,
            "download_state": (
                "downloading"
                if get_download_state() is DownloadState.Downloading
                else "paused"
            ),
            "summary": {
                "speed": f"{format_byte(get_total_download_speed())}/s",
                "speed_bytes": get_total_download_speed(),
                "active_count": get_active_download_count(),
                "queue_count": sum(
                    max(int(task.get("total", 0)) - int(task.get("finished", 0)), 0)
                    for task in tasks
                ),
                "completed_count": len(completed_downloads),
                "task_count": len(tasks),
                "bot_enabled": bool(app.bot_token),
                "clash_enabled": bool(app.clash_config.get("enabled", True)),
            },
            "downloads": active_downloads,
            "completed": completed_downloads[-100:],
            "tasks": tasks,
            "bot": {
                "enabled": bool(app.bot_token),
                "task_count": len([it for it in tasks if it.get("source") == "bot"]),
                "last_messages": [
                    {
                        "task_id": task.get("task_id"),
                        "chat_id": task.get("chat_id"),
                        "message": task.get("last_bot_message", ""),
                    }
                    for task in tasks
                    if task.get("last_bot_message")
                ][-10:],
            },
            "config_preview": {
                "save_path": app.save_path,
                "language": app.language.name,
                "max_download_task": app.max_download_task,
                "scan_prefetch_limit": app.scan_prefetch_limit,
                "clash": {
                    "enabled": bool(app.clash_config.get("enabled", True)),
                    "controller": app.clash_config.get("controller", ""),
                    "selector": app.clash_config.get("selector", ""),
                    "low_speed_kb": app.clash_config.get("low_speed_kb", 100),
                    "low_speed_seconds": app.clash_config.get(
                        "low_speed_seconds", 60
                    ),
                },
            },
        }
    )


@_flask_app.route("/api/config", methods=["GET", "POST"])
@login_required
def api_config():
    """Read or update editable config values."""
    app = _get_runtime_app()
    if request.method == "GET":
        return jsonify(_public_config(app))

    data = request.get_json(silent=True) or {}
    restart_required = _save_public_config(app, data)
    return jsonify(
        {
            "ok": True,
            "restart_required": restart_required,
            "config": _public_config(app),
        }
    )


@_flask_app.route("/get_app_version")
def get_app_version():
    """Get telegram_media_downloader version"""
    return utils.__version__


@_flask_app.route("/get_download_list")
@login_required
def get_download_list():
    """get download list"""
    if request.args.get("already_down") is None:
        return "[]"

    already_down = request.args.get("already_down") == "true"

    download_result = get_download_result()
    result = "["
    for chat_id, messages in download_result.items():
        for idx, value in messages.items():
            is_already_down = value["down_byte"] == value["total_size"]

            if already_down and not is_already_down:
                continue

            if result != "[":
                result += ","
            download_speed = format_byte(value["download_speed"]) + "/s"
            result += (
                '{ "chat":"'
                + f"{chat_id}"
                + '", "id":"'
                + f"{idx}"
                + '", "filename":"'
                + os.path.basename(value["file_name"])
                + '", "total_size":"'
                + f'{format_byte(value["total_size"])}'
                + '" ,"download_progress":"'
            )
            result += (
                f'{round(value["down_byte"] / value["total_size"] * 100, 1)}'
                + '" ,"download_speed":"'
                + download_speed
                + '" ,"save_path":"'
                + value["file_name"].replace("\\", "/")
                + '"}'
            )

    result += "]"
    return result
