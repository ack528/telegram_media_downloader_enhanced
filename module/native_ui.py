"""Native desktop UI for Telegram Media Downloader."""

from __future__ import annotations

import asyncio
import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from module.app import Application, DownloadStatus
from module.download_stat import (
    DownloadState,
    get_active_download_count,
    get_download_result,
    get_download_state,
    get_total_download_speed,
    set_download_state,
)
from module.language import Language
from utils.format import format_byte


POLL_INTERVAL_MS = 1000
COLOR_BG = "#ffffff"
COLOR_PANEL = "#ffffff"
COLOR_PANEL_ALT = "#ffffff"
COLOR_BORDER = "#d1d5db"
COLOR_TEXT = "#0f172a"
COLOR_MUTED = "#6b7280"
COLOR_PRIMARY = "#f97316"
COLOR_PRIMARY_DARK = "#ea580c"
COLOR_PROGRESS = "#f97316"
COLOR_SOFT_BLUE = "#f3f4f6"
COLOR_SOFT_BLUE_ACTIVE = "#e5e7eb"
COLOR_INPUT_BG = "#ffffff"
COLOR_LOG_BG = "#ffffff"
COLOR_LOG_FG = "#0f172a"


def resource_path(relative_path: str) -> str:
    """Resolve resources both from source checkout and PyInstaller one-file builds."""
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def bind_core_event_loop(core_module):
    """Bind the downloader event loop to the current thread before Pyrogram starts."""
    asyncio.set_event_loop(core_module.app.loop)


def enable_high_dpi_awareness():
    """Enable Windows high-DPI rendering before Tk creates widgets."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def format_percent(done: int, total: int) -> str:
    """Format progress as a percent string."""
    if total <= 0:
        return "0%"
    return f"{min(done / total * 100, 100):.1f}%"


def collect_download_rows() -> list[dict[str, Any]]:
    """Return current file download rows for the UI."""
    rows = []
    for chat_id, messages in get_download_result().items():
        for message_id, value in messages.items():
            total_size = int(value.get("total_size") or 0)
            down_byte = int(value.get("down_byte") or 0)
            is_done = total_size > 0 and down_byte >= total_size
            percent_value = min(down_byte / total_size * 100, 100) if total_size else 0
            rows.append(
                {
                    "key": f"{chat_id}:{message_id}",
                    "task_id": value.get("task_id", ""),
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "file_name": os.path.basename(str(value.get("file_name", ""))),
                    "percent_value": percent_value,
                    "progress": format_percent(down_byte, total_size),
                    "downloaded": format_byte(down_byte),
                    "total": format_byte(total_size),
                    "speed": f"{format_byte(value.get('download_speed', 0))}/s",
                    "status": "完成" if is_done else "下载中",
                    "path": str(value.get("file_name", "")),
                    "updated_at": float(value.get("end_time") or 0),
                }
            )
    return sorted(
        rows,
        key=lambda item: (
            item["status"] == "完成",
            item["chat_id"],
            int(item["message_id"] or 0),
        ),
    )


def collect_task_rows(app: Application) -> list[dict[str, Any]]:
    """Return runtime download task rows."""
    rows = []
    for chat_id, config in app.chat_download_config.items():
        node = getattr(config, "node", None)
        status_map = getattr(node, "download_status", {}) if node else {}
        total = int(getattr(node, "total_task", 0) or getattr(config, "total_task", 0))
        finished = int(
            getattr(node, "total_download_task", 0)
            or getattr(config, "finish_task", 0)
        )
        success = sum(
            1 for status in status_map.values() if status is DownloadStatus.SuccessDownload
        )
        failed = sum(
            1 for status in status_map.values() if status is DownloadStatus.FailedDownload
        )
        skipped = sum(
            1 for status in status_map.values() if status is DownloadStatus.SkipDownload
        )
        rows.append(
            {
                "task_id": getattr(node, "task_id", ""),
                "source": "机器人" if getattr(config, "is_bot_task", False) else "配置",
                "chat_key": chat_id,
                "chat_id": str(chat_id),
                "progress": format_percent(finished, total),
                "finished": finished,
                "total": total,
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "pending_retry": len(getattr(config, "ids_to_retry", []) or []),
                "running": bool(getattr(node, "is_running", False)),
                "last_bot_message": getattr(node, "last_edit_msg", "") if node else "",
            }
        )
    return rows


def collect_dashboard_snapshot(app: Application) -> dict[str, Any]:
    """Return a small dashboard snapshot for tests and UI rendering."""
    downloads = collect_download_rows()
    tasks = collect_task_rows(app)
    finished_count = sum(1 for row in downloads if row["status"] == "完成")
    return {
        "speed": f"{format_byte(get_total_download_speed())}/s",
        "active_count": get_active_download_count(),
        "download_state": (
            "downloading" if get_download_state() is DownloadState.Downloading else "paused"
        ),
        "download_count": len(downloads),
        "finished_count": finished_count,
        "task_count": len(tasks),
        "bot_enabled": bool(app.bot_token),
        "clash_enabled": bool(app.clash_config.get("enabled", True)),
        "save_path": app.save_path,
        "config_file": app.config_file,
    }


def apply_config_changes(app: Application, values: dict[str, Any]) -> list[str]:
    """Apply editable config values and persist config.yaml."""
    if not app.config:
        raise ValueError("配置尚未加载完成，请稍后再保存。")

    restart_required = []

    def get_int(name: str, default: int, minimum: int = 0) -> int:
        try:
            return max(int(values.get(name, default)), minimum)
        except (TypeError, ValueError):
            return default

    def get_plain_int(value: Any, default: int, minimum: int = 0) -> int:
        try:
            return max(int(value), minimum)
        except (TypeError, ValueError):
            return default

    if "language" in values:
        language = str(values.get("language") or app.language.name).upper()
        if language in Language.__members__:
            app.set_language(Language[language])
            app.config["language"] = app.language.name

    for key in ("save_path", "log_level"):
        if key in values:
            value = str(values.get(key) or "")
            setattr(app, key, value)
            app.config[key] = value

    int_fields = {
        "max_download_task": 1,
        "max_concurrent_transmissions": 1,
        "scan_prefetch_limit": 0,
        "download_stall_timeout": 1,
        "history_fetch_timeout": 1,
        "history_fetch_retries": 1,
    }
    for key, minimum in int_fields.items():
        if key in values:
            value = get_int(key, getattr(app, key), minimum)
            setattr(app, key, value)
            app.config[key] = value
            if key == "max_download_task":
                restart_required.append(key)

    clash_values = values.get("clash")
    if isinstance(clash_values, dict):
        for key, value in clash_values.items():
            if key in (
                "low_speed_kb",
                "low_speed_seconds",
                "switch_cooldown_seconds",
                "timeout_ms",
            ):
                value = get_plain_int(value, app.clash_config.get(key, 0), 0)
            app.clash_config[key] = value
        app.config["clash"] = dict(app.clash_config)

    app.persist_config_file()
    return sorted(set(restart_required))


def delete_task(app: Application, chat_id: Any) -> bool:
    """Delete a runtime task and persist recovery data."""
    return app.remove_download_task(chat_id)


class NativeDownloaderUI:
    """Tkinter/ttk control panel that runs the downloader in a background thread."""

    def __init__(self, core_module):
        self.core = core_module
        self.app: Application = core_module.app
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.started = False
        self.config_loaded = False
        self.config_vars: dict[str, tk.Variable] = {}
        self.clash_vars: dict[str, tk.Variable] = {}
        self.task_row_keys: dict[str, Any] = {}
        self.download_cards: dict[str, dict[str, Any]] = {}

        enable_high_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("Telegram Media Downloader")
        self.root.geometry("1240x800")
        self.root.minsize(1080, 700)
        self._apply_window_icon()
        self._apply_scaling()
        self._build_style()
        self._build_ui()
        self._wire_logger()

    def _apply_window_icon(self):
        icon_path = resource_path(os.path.join("assets", "tdl_logo.ico"))
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except tk.TclError:
                pass

    def _apply_scaling(self):
        try:
            dpi = self.root.winfo_fpixels("1i")
            self.root.tk.call("tk", "scaling", max(dpi / 72, 1.0))
        except Exception:
            pass

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.configure(bg=COLOR_BG)
        style.configure(".", font=("Microsoft YaHei UI", 10), background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("PanelAlt.TFrame", background=COLOR_PANEL_ALT)
        style.configure("Header.TFrame", background=COLOR_BG)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"), background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 10), background=COLOR_BG, foreground=COLOR_MUTED)
        style.configure("Metric.TLabel", font=("Microsoft YaHei UI", 16, "bold"), background=COLOR_PANEL, foreground=COLOR_PRIMARY_DARK)
        style.configure("MetricName.TLabel", font=("Microsoft YaHei UI", 9), background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure("Card.TLabelframe", background=COLOR_PANEL, bordercolor=COLOR_BORDER, relief="flat")
        style.configure("Card.TLabelframe.Label", background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure("Download.TFrame", background=COLOR_PANEL)
        style.configure("DownloadTitle.TLabel", font=("Microsoft YaHei UI", 10, "bold"), background=COLOR_PANEL, foreground=COLOR_TEXT)
        style.configure("DownloadMeta.TLabel", font=("Microsoft YaHei UI", 9), background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TButton", padding=(14, 6), background=COLOR_SOFT_BLUE, foreground=COLOR_TEXT, bordercolor=COLOR_SOFT_BLUE, relief="flat")
        style.map("TButton", background=[("pressed", COLOR_SOFT_BLUE_ACTIVE), ("active", COLOR_SOFT_BLUE_ACTIVE), ("disabled", "#edf2f8")], foreground=[("disabled", "#94a3b8")], relief=[("pressed", "flat"), ("active", "flat")])
        style.configure("Primary.TButton", padding=(16, 7), background=COLOR_PRIMARY, foreground="#ffffff", bordercolor=COLOR_PRIMARY, relief="flat")
        style.map("Primary.TButton", background=[("pressed", COLOR_PRIMARY_DARK), ("active", COLOR_PRIMARY_DARK), ("disabled", "#a7d8f2")], foreground=[("disabled", "#eef8ff")], relief=[("pressed", "flat"), ("active", "flat")])
        style.configure("TEntry", fieldbackground=COLOR_INPUT_BG, foreground=COLOR_TEXT, bordercolor="#cbd5e1", lightcolor="#cbd5e1", darkcolor="#cbd5e1", insertcolor=COLOR_PRIMARY, padding=(6, 4))
        style.configure("TCombobox", fieldbackground=COLOR_INPUT_BG, foreground=COLOR_TEXT, bordercolor="#cbd5e1", arrowcolor=COLOR_PRIMARY, padding=(6, 4))
        style.map("TCombobox", fieldbackground=[("readonly", COLOR_INPUT_BG)], selectbackground=[("readonly", "#f3f4f6")])
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
        style.configure("TNotebook.Tab", padding=(16, 8), background="#f3f4f6", foreground=COLOR_TEXT, borderwidth=0, relief="flat", focuscolor="#f3f4f6")
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLOR_PANEL), ("active", COLOR_SOFT_BLUE_ACTIVE), ("pressed", COLOR_SOFT_BLUE_ACTIVE)],
            foreground=[("selected", COLOR_PRIMARY_DARK), ("active", COLOR_TEXT)],
            padding=[("selected", (16, 8)), ("active", (16, 8)), ("pressed", (16, 8))],
            relief=[("selected", "flat"), ("pressed", "flat"), ("active", "flat")],
        )
        style.layout(
            "TNotebook.Tab",
            [
                (
                    "Notebook.tab",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Notebook.padding",
                                {
                                    "side": "top",
                                    "sticky": "nswe",
                                    "children": [("Notebook.label", {"side": "top", "sticky": ""})],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.configure("Blue.Horizontal.TProgressbar", troughcolor="#e2e8f0", background=COLOR_PROGRESS, bordercolor="#e2e8f0", lightcolor=COLOR_PROGRESS, darkcolor=COLOR_PROGRESS)
        style.configure("Treeview", rowheight=28, background=COLOR_PANEL, fieldbackground=COLOR_PANEL, foreground=COLOR_TEXT, bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER)
        style.configure("Treeview.Heading", background="#f3f4f6", foreground=COLOR_TEXT)

    def _build_ui(self):
        shell = ttk.Frame(self.root, padding=(14, 12))
        shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(shell, style="Header.TFrame")
        header.pack(fill=tk.X)
        title_box = ttk.Frame(header)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title_box, text="Telegram Media Downloader", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(title_box, text="清爽控制台 · 实时任务 / 下载 / 配置", style="Subtitle.TLabel").pack(anchor=tk.W, pady=(2, 0))
        self.state_label = ttk.Label(header, text="准备启动", style="Subtitle.TLabel")
        self.state_label.pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self._build_overview_tab()
        self._build_download_tab()
        self._build_bot_tab()
        self._build_config_tab()
        self._build_log_tab()

        footer = ttk.Frame(shell)
        footer.pack(fill=tk.X, pady=(8, 0))
        self.pause_button = ttk.Button(
            footer,
            text="暂停下载",
            style="Primary.TButton",
            command=self.toggle_download_state,
        )
        self.pause_button.pack(side=tk.LEFT, ipadx=10)
        ttk.Button(footer, text="退出", command=self.close, width=12).pack(side=tk.RIGHT)

    def _build_overview_tab(self):
        tab = ttk.Frame(self.notebook, padding=(10, 10))
        self.notebook.add(tab, text="总览")
        metrics = ttk.Frame(tab)
        metrics.pack(fill=tk.X)
        self.metric_vars = {
            "speed": tk.StringVar(value="0 B/s"),
            "active": tk.StringVar(value="0"),
            "tasks": tk.StringVar(value="0"),
            "finished": tk.StringVar(value="0"),
            "bot": tk.StringVar(value="未启用"),
            "clash": tk.StringVar(value="启用"),
        }
        for title, key in (
            ("总下载速度", "speed"),
            ("活跃文件", "active"),
            ("运行任务", "tasks"),
            ("完成文件", "finished"),
            ("机器人", "bot"),
            ("Clash", "clash"),
        ):
            card = ttk.LabelFrame(metrics, text=title, padding=(10, 8), style="Card.TLabelframe")
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
            ttk.Label(card, textvariable=self.metric_vars[key], style="Metric.TLabel").pack(anchor=tk.W)

        detail_panel = ttk.Frame(tab, style="Panel.TFrame", padding=(10, 8))
        detail_panel.pack(fill=tk.X, pady=(10, 0))
        self.overview_detail_vars = {
            "state": tk.StringVar(value="状态：准备启动"),
            "save_path": tk.StringVar(value="保存目录：-"),
            "config_file": tk.StringVar(value="配置文件：-"),
        }
        for variable in self.overview_detail_vars.values():
            ttk.Label(detail_panel, textvariable=variable, style="DownloadMeta.TLabel").pack(anchor=tk.W, pady=2)

        self.startup_text = tk.Text(tab, height=10, wrap=tk.WORD, font=("Microsoft YaHei UI", 9))
        self.startup_text.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.startup_text.configure(bg=COLOR_PANEL, fg=COLOR_TEXT, insertbackground=COLOR_PRIMARY, relief=tk.FLAT, padx=10, pady=8)
        self.startup_text.insert(tk.END, "启动准备中：等待读取 config.yaml...\n")
        self.startup_text.configure(state=tk.DISABLED)

    def _build_download_tab(self):
        tab = ttk.Frame(self.notebook, padding=(10, 10))
        self.notebook.add(tab, text="文件下载")
        header = ttk.Frame(tab)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, text="文件下载进度", style="DownloadTitle.TLabel").pack(side=tk.LEFT)
        self.download_summary_var = tk.StringVar(value="暂无下载任务")
        ttk.Label(header, textvariable=self.download_summary_var, style="DownloadMeta.TLabel").pack(side=tk.RIGHT)

        self.download_canvas = tk.Canvas(
            tab,
            bg=COLOR_PANEL_ALT,
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.download_canvas.yview)
        self.download_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.download_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.download_list_frame = ttk.Frame(self.download_canvas)
        self.download_canvas_window = self.download_canvas.create_window(
            (0, 0), window=self.download_list_frame, anchor="nw"
        )
        self.download_list_frame.bind(
            "<Configure>",
            lambda _event: self.download_canvas.configure(
                scrollregion=self.download_canvas.bbox("all")
            ),
        )
        self.download_canvas.bind("<Configure>", self._resize_download_canvas)
        self.download_canvas.bind_all("<MouseWheel>", self._on_download_mousewheel)
        self.download_empty_label = ttk.Label(
            self.download_list_frame,
            text="暂无文件下载。收到任务后会在这里显示实时进度。",
            style="DownloadMeta.TLabel",
        )
        self.download_empty_label.pack(fill=tk.X, pady=16)

    def _build_bot_tab(self):
        tab = ttk.Frame(self.notebook, padding=(10, 10))
        self.notebook.add(tab, text="机器人/任务")
        columns = (
            "task",
            "source",
            "chat",
            "progress",
            "success",
            "failed",
            "pending",
            "running",
        )
        self.task_tree = ttk.Treeview(tab, columns=columns, show="headings", height=6)
        headings = {
            "task": "任务",
            "source": "来源",
            "chat": "会话",
            "progress": "完成",
            "success": "成功",
            "failed": "失败",
            "pending": "待恢复",
            "running": "运行中",
        }
        column_widths = {
            "task": 80,
            "source": 90,
            "chat": 190,
            "progress": 130,
            "success": 80,
            "failed": 80,
            "pending": 95,
            "running": 85,
        }
        for key in columns:
            self.task_tree.heading(key, text=headings[key])
            self.task_tree.column(
                key,
                width=column_widths[key],
                minwidth=60,
                anchor=tk.W,
                stretch=key in {"chat", "progress"},
            )
        self.task_tree.pack(fill=tk.X)

        task_actions = ttk.Frame(tab)
        task_actions.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(task_actions, text="删除选中任务", command=self.delete_selected_task, width=14).pack(
            side=tk.LEFT
        )
        self.task_tree.bind("<Delete>", lambda _event: self.delete_selected_task())

        ttk.Label(tab, text="机器人最近状态消息").pack(anchor=tk.W, pady=(10, 4))
        self.bot_message_text = tk.Text(
            tab,
            height=9,
            wrap=tk.WORD,
            font=("Microsoft YaHei UI", 9),
        )
        self.bot_message_text.configure(
            bg=COLOR_PANEL,
            fg=COLOR_TEXT,
            insertbackground=COLOR_PRIMARY,
            relief=tk.FLAT,
            padx=10,
            pady=8,
        )
        self.bot_message_text.pack(fill=tk.BOTH, expand=True)

    def _build_config_tab(self):
        tab = ttk.Frame(self.notebook, padding=(10, 10))
        self.notebook.add(tab, text="配置")
        grid = ttk.Frame(tab)
        grid.pack(fill=tk.X)

        fields = (
            ("language", "语言"),
            ("save_path", "保存路径"),
            ("max_download_task", "最大下载任务"),
            ("max_concurrent_transmissions", "并发传输数"),
            ("scan_prefetch_limit", "扫描预取上限"),
            ("download_stall_timeout", "下载卡住超时秒"),
            ("history_fetch_timeout", "历史读取超时秒"),
            ("history_fetch_retries", "历史读取重试"),
            ("log_level", "日志等级"),
        )
        for index, (key, title) in enumerate(fields):
            row = index // 2
            col = (index % 2) * 2
            ttk.Label(grid, text=title).grid(row=row, column=col, sticky=tk.W, pady=5)
            var = tk.StringVar()
            self.config_vars[key] = var
            widget: ttk.Widget
            if key == "language":
                widget = ttk.Combobox(
                    grid, textvariable=var, values=("ZH", "EN"), state="readonly"
                )
            elif key == "save_path":
                path_frame = ttk.Frame(grid)
                entry = ttk.Entry(path_frame, textvariable=var)
                entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
                ttk.Button(
                    path_frame,
                    text="选择...",
                    command=lambda variable=var: self.choose_directory(variable),
                ).pack(side=tk.LEFT, padx=(6, 0))
                widget = path_frame
            else:
                widget = ttk.Entry(grid, textvariable=var)
            widget.grid(row=row, column=col + 1, sticky=tk.EW, padx=(8, 18), pady=5)
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        clash = ttk.LabelFrame(tab, text="Clash 自动切换", padding=(10, 8))
        clash.pack(fill=tk.X, pady=(10, 0))
        clash_fields = (
            ("enabled", "启用"),
            ("controller", "外部控制地址"),
            ("secret", "API 密钥"),
            ("selector", "代理组 selector"),
            ("low_speed_kb", "低速阈值 KB/s"),
            ("low_speed_seconds", "低速持续秒"),
            ("switch_cooldown_seconds", "切换冷却秒"),
            ("timeout_ms", "测速超时毫秒"),
        )
        for index, (key, title) in enumerate(clash_fields):
            row = index // 2
            col = (index % 2) * 2
            ttk.Label(clash, text=title).grid(row=row, column=col, sticky=tk.W, pady=5)
            var = tk.StringVar()
            self.clash_vars[key] = var
            if key == "enabled":
                widget = ttk.Combobox(
                    clash, textvariable=var, values=("true", "false"), state="readonly"
                )
            else:
                widget = ttk.Entry(clash, textvariable=var, show="*" if key == "secret" else "")
            widget.grid(row=row, column=col + 1, sticky=tk.EW, padx=(8, 18), pady=5)
        clash.columnconfigure(1, weight=1)
        clash.columnconfigure(3, weight=1)

        ttk.Label(
            tab,
            text="复杂的 chat / media_types / file_formats 仍建议直接编辑 config.yaml。",
        ).pack(anchor=tk.W, pady=(10, 0))

        config_actions = ttk.Frame(tab)
        config_actions.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(
            config_actions,
            text="保存配置",
            command=self.save_config,
            style="Primary.TButton",
            width=14,
        ).pack(side=tk.RIGHT)

    def _build_log_tab(self):
        tab = ttk.Frame(self.notebook, padding=(10, 10))
        self.notebook.add(tab, text="运行日志")
        self.log_text = tk.Text(tab, wrap=tk.WORD, font=("Microsoft YaHei UI", 9))
        self.log_text.configure(bg=COLOR_LOG_BG, fg=COLOR_LOG_FG, insertbackground=COLOR_PROGRESS, relief=tk.FLAT, padx=10, pady=8)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _wire_logger(self):
        def sink(message):
            self.log_queue.put(str(message))

        self.core.logger.add(sink, level="INFO")

    def start(self):
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.start_downloader)
        self.root.after(300, self.poll)
        self.root.mainloop()

    def start_downloader(self):
        if self.started:
            return
        self.started = True
        self._append_startup("准备读取配置和启动 Telegram 客户端...\n")
        self.worker_thread = threading.Thread(target=self._run_core, daemon=True)
        self.worker_thread.start()

    def _run_core(self):
        try:
            bind_core_event_loop(self.core)
            if self.core._check_config():
                self.config_loaded = True
                self._load_config_vars()
                self.core.main()
            else:
                self.log_queue.put("配置检查失败，请检查 config.yaml。\n")
        except Exception as exc:
            self.log_queue.put(f"程序异常退出：{exc}\n")

    def _load_config_vars(self):
        def load():
            for key, var in self.config_vars.items():
                value = getattr(self.app, key, "")
                if key == "language":
                    value = self.app.language.name
                var.set(str(value))
            for key, var in self.clash_vars.items():
                value = self.app.clash_config.get(key, "")
                if isinstance(value, bool):
                    value = str(value).lower()
                var.set(str(value))

        self.root.after(0, load)

    def poll(self):
        self._flush_logs()
        self._refresh_metrics()
        self._refresh_downloads()
        self._refresh_tasks()
        self.root.after(POLL_INTERVAL_MS, self.poll)

    def _flush_logs(self):
        while True:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_text(self.log_text, item)
            self._append_startup(item)

    def _append_startup(self, text: str):
        self.startup_text.configure(state=tk.NORMAL)
        self.startup_text.insert(tk.END, text)
        self.startup_text.see(tk.END)
        self.startup_text.configure(state=tk.DISABLED)

    @staticmethod
    def _append_text(widget: tk.Text, text: str):
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, text)
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _refresh_metrics(self):
        snapshot = collect_dashboard_snapshot(self.app)
        self.metric_vars["speed"].set(snapshot["speed"])
        self.metric_vars["active"].set(str(snapshot["active_count"]))
        self.metric_vars["tasks"].set(str(snapshot["task_count"]))
        self.metric_vars["finished"].set(
            f"{snapshot['finished_count']}/{snapshot['download_count']}"
        )
        self.metric_vars["bot"].set("启用" if snapshot["bot_enabled"] else "未启用")
        self.metric_vars["clash"].set("启用" if snapshot["clash_enabled"] else "关闭")
        state_text = "下载中" if snapshot["download_state"] == "downloading" else "已暂停"
        self.state_label.configure(
            text=state_text
        )
        self.overview_detail_vars["state"].set(
            f"状态：{state_text} · 文件 {snapshot['finished_count']}/{snapshot['download_count']} · 活跃 {snapshot['active_count']}"
        )
        self.overview_detail_vars["save_path"].set(f"保存目录：{snapshot['save_path']}")
        self.overview_detail_vars["config_file"].set(f"配置文件：{snapshot['config_file']}")
        self.pause_button.configure(
            text="暂停下载" if snapshot["download_state"] == "downloading" else "继续下载"
        )

    def _refresh_downloads(self):
        rows = collect_download_rows()
        self.download_summary_var.set(
            f"{len(rows)} 个文件 · {get_active_download_count()} 个活跃 · {format_byte(get_total_download_speed())}/s"
            if rows
            else "暂无下载任务"
        )
        self._sync_download_cards(rows)

    def _resize_download_canvas(self, event):
        self.download_canvas.itemconfigure(self.download_canvas_window, width=event.width)

    def _on_download_mousewheel(self, event):
        if self.notebook.index(self.notebook.select()) == 1:
            self.download_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _create_download_card(self, row: dict[str, Any]) -> dict[str, Any]:
        frame = ttk.Frame(self.download_list_frame, style="Download.TFrame", padding=12)
        frame.pack(fill=tk.X, pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        title = ttk.Label(frame, text=row["file_name"] or "-", style="DownloadTitle.TLabel")
        title.grid(row=0, column=0, sticky=tk.EW)
        status = ttk.Label(frame, text=row["status"], style="DownloadMeta.TLabel")
        status.grid(row=0, column=1, sticky=tk.E, padx=(12, 0))

        meta = ttk.Label(frame, style="DownloadMeta.TLabel")
        meta.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(4, 8))

        progress = ttk.Progressbar(
            frame,
            maximum=100,
            mode="determinate",
            style="Blue.Horizontal.TProgressbar",
        )
        progress.grid(row=2, column=0, sticky=tk.EW)
        percent = ttk.Label(frame, width=8, anchor=tk.E, style="DownloadMeta.TLabel")
        percent.grid(row=2, column=1, sticky=tk.E, padx=(12, 0))

        path = ttk.Label(frame, style="DownloadMeta.TLabel")
        path.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))

        card = {
            "frame": frame,
            "title": title,
            "status": status,
            "meta": meta,
            "progress": progress,
            "percent": percent,
            "path": path,
        }
        self._update_download_card(card, row)
        return card

    @staticmethod
    def _update_download_card(card: dict[str, Any], row: dict[str, Any]):
        card["title"].configure(text=row["file_name"] or "-")
        card["status"].configure(text=row["status"])
        card["meta"].configure(
            text=(
                f"任务 {row['task_id']} · 会话 {row['chat_id']} · 消息 {row['message_id']} · "
                f"{row['downloaded']} / {row['total']} · {row['speed']}"
            )
        )
        card["progress"]["value"] = row["percent_value"]
        card["percent"].configure(text=row["progress"])
        card["path"].configure(text=row["path"])

    def _sync_download_cards(self, rows: list[dict[str, Any]]):
        if rows:
            self.download_empty_label.pack_forget()
        else:
            if not self.download_empty_label.winfo_ismapped():
                self.download_empty_label.pack(fill=tk.X, pady=16)

        current_keys = {row["key"] for row in rows}
        for key in list(self.download_cards):
            if key not in current_keys:
                self.download_cards[key]["frame"].destroy()
                self.download_cards.pop(key, None)

        for row in rows:
            card = self.download_cards.get(row["key"])
            if card is None:
                self.download_cards[row["key"]] = self._create_download_card(row)
            else:
                self._update_download_card(card, row)

    def _refresh_tasks(self):
        rows = collect_task_rows(self.app)
        self.task_row_keys = {}
        self._replace_tree_rows(
            self.task_tree,
            [
                (
                    row["task_id"],
                    row["source"],
                    row["chat_id"],
                    f"{row['finished']}/{row['total']} ({row['progress']})",
                    row["success"],
                    row["failed"],
                    row["pending_retry"],
                    "是" if row["running"] else "否",
                )
                for row in rows
            ],
        )
        for item, row in zip(self.task_tree.get_children(), rows):
            self.task_row_keys[item] = row["chat_key"]
        messages = [row["last_bot_message"] for row in rows if row["last_bot_message"]]
        self.bot_message_text.configure(state=tk.NORMAL)
        self.bot_message_text.delete("1.0", tk.END)
        self.bot_message_text.insert(tk.END, "\n\n".join(messages[-5:]) or "暂无机器人状态消息")
        self.bot_message_text.configure(state=tk.DISABLED)

    @staticmethod
    def _replace_tree_rows(tree: ttk.Treeview, rows: list[tuple]):
        existing = tree.get_children()
        for item in existing:
            tree.delete(item)
        for row in rows:
            tree.insert("", tk.END, values=row)

    def toggle_download_state(self):
        if get_download_state() is DownloadState.Downloading:
            set_download_state(DownloadState.StopDownload)
        else:
            set_download_state(DownloadState.Downloading)
        self._refresh_metrics()

    def save_config(self):
        if not self.config_loaded or not self.app.config:
            messagebox.showwarning(
                "配置尚未加载",
                "请等待启动准备完成并成功读取 config.yaml 后再保存配置。",
            )
            return

        values: dict[str, Any] = {
            key: var.get() for key, var in self.config_vars.items()
        }
        clash = {key: var.get() for key, var in self.clash_vars.items()}
        clash["enabled"] = str(clash.get("enabled", "true")).lower() == "true"
        values["clash"] = clash
        try:
            restart_required = apply_config_changes(self.app, values)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return

        if restart_required:
            messagebox.showinfo(
                "配置已保存",
                "配置已写入 config.yaml。以下设置需要重启软件完全生效："
                + ", ".join(restart_required),
            )
        else:
            messagebox.showinfo("配置已保存", "配置已写入 config.yaml。")

    def choose_directory(self, variable: tk.Variable):
        initial_dir = str(variable.get() or self.app.base_path)
        if not os.path.isdir(initial_dir):
            initial_dir = self.app.base_path
        selected = filedialog.askdirectory(
            parent=self.root,
            title="选择保存目录",
            initialdir=initial_dir,
            mustexist=False,
        )
        if selected:
            variable.set(selected)

    def delete_selected_task(self):
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showinfo("删除任务", "请先在任务列表中选择一个任务。")
            return

        deleted = 0
        for item in selected:
            chat_id = self.task_row_keys.get(item)
            if chat_id is None:
                continue
            if messagebox.askyesno(
                "删除任务",
                f"确定删除任务 chat_id={chat_id} 吗？当前下载会停止，"
                "异常恢复记录和 config.yaml 中对应的 chat 配置也会移除。",
            ):
                if delete_task(self.app, chat_id):
                    deleted += 1

        if deleted:
            self._refresh_tasks()
            self._append_startup(f"已删除 {deleted} 个任务。\n")

    def close(self):
        if messagebox.askokcancel("退出", "确定要退出下载器吗？"):
            self.app.is_running = False
            self.root.after(300, self.root.destroy)


def run_native_ui(core_module):
    """Run the native desktop UI."""
    NativeDownloaderUI(core_module).start()
