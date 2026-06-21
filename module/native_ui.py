"""Native desktop UI for Telegram Media Downloader."""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
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
            rows.append(
                {
                    "task_id": value.get("task_id", ""),
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "file_name": os.path.basename(str(value.get("file_name", ""))),
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
    return {
        "speed": f"{format_byte(get_total_download_speed())}/s",
        "active_count": get_active_download_count(),
        "download_state": (
            "downloading" if get_download_state() is DownloadState.Downloading else "paused"
        ),
        "download_count": len(downloads),
        "task_count": len(tasks),
        "bot_enabled": bool(app.bot_token),
        "clash_enabled": bool(app.clash_config.get("enabled", True)),
    }


def apply_config_changes(app: Application, values: dict[str, Any]) -> list[str]:
    """Apply editable config values and persist config.yaml."""
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

    app.update_config(True)
    return sorted(set(restart_required))


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

        enable_high_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("Telegram Media Downloader")
        self.root.geometry("1180x760")
        self.root.minsize(980, 620)
        self._apply_scaling()
        self._build_style()
        self._build_ui()
        self._wire_logger()

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
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Metric.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Primary.TButton", padding=(14, 8))
        style.configure("Treeview", rowheight=30)

    def _build_ui(self):
        shell = ttk.Frame(self.root, padding=16)
        shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(shell)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Telegram Media Downloader", style="Title.TLabel").pack(
            side=tk.LEFT
        )
        self.state_label = ttk.Label(header, text="准备启动")
        self.state_label.pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        self._build_overview_tab()
        self._build_download_tab()
        self._build_bot_tab()
        self._build_config_tab()
        self._build_log_tab()

        footer = ttk.Frame(shell)
        footer.pack(fill=tk.X, pady=(12, 0))
        self.pause_button = ttk.Button(
            footer,
            text="暂停下载",
            style="Primary.TButton",
            command=self.toggle_download_state,
        )
        self.pause_button.pack(side=tk.LEFT)
        ttk.Button(footer, text="保存配置", command=self.save_config).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(footer, text="退出", command=self.close).pack(side=tk.RIGHT)

    def _build_overview_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="总览")
        metrics = ttk.Frame(tab)
        metrics.pack(fill=tk.X)
        self.metric_vars = {
            "speed": tk.StringVar(value="0 B/s"),
            "active": tk.StringVar(value="0"),
            "tasks": tk.StringVar(value="0"),
            "bot": tk.StringVar(value="未启用"),
            "clash": tk.StringVar(value="启用"),
        }
        for title, key in (
            ("总下载速度", "speed"),
            ("活跃文件", "active"),
            ("运行任务", "tasks"),
            ("机器人", "bot"),
            ("Clash", "clash"),
        ):
            card = ttk.LabelFrame(metrics, text=title, padding=12)
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
            ttk.Label(card, textvariable=self.metric_vars[key], style="Metric.TLabel").pack(
                anchor=tk.W
            )

        self.startup_text = tk.Text(tab, height=13, wrap=tk.WORD)
        self.startup_text.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        self.startup_text.insert(tk.END, "启动准备中：等待读取 config.yaml...\n")
        self.startup_text.configure(state=tk.DISABLED)

    def _build_download_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="文件下载")
        columns = (
            "task",
            "chat",
            "message",
            "file",
            "progress",
            "size",
            "speed",
            "status",
            "path",
        )
        self.download_tree = ttk.Treeview(tab, columns=columns, show="headings")
        headings = {
            "task": "任务",
            "chat": "会话",
            "message": "消息ID",
            "file": "文件",
            "progress": "进度",
            "size": "大小",
            "speed": "速度",
            "status": "状态",
            "path": "保存路径",
        }
        widths = {
            "task": 70,
            "chat": 130,
            "message": 80,
            "file": 220,
            "progress": 90,
            "size": 130,
            "speed": 110,
            "status": 80,
            "path": 320,
        }
        for key in columns:
            self.download_tree.heading(key, text=headings[key])
            self.download_tree.column(key, width=widths[key], anchor=tk.W)
        self.download_tree.pack(fill=tk.BOTH, expand=True)

    def _build_bot_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
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
        self.task_tree = ttk.Treeview(tab, columns=columns, show="headings", height=9)
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
        for key in columns:
            self.task_tree.heading(key, text=headings[key])
            self.task_tree.column(key, width=120, anchor=tk.W)
        self.task_tree.pack(fill=tk.X)

        ttk.Label(tab, text="机器人最近状态消息").pack(anchor=tk.W, pady=(14, 4))
        self.bot_message_text = tk.Text(tab, height=14, wrap=tk.WORD)
        self.bot_message_text.pack(fill=tk.BOTH, expand=True)

    def _build_config_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
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
            ttk.Label(grid, text=title).grid(row=row, column=col, sticky=tk.W, pady=6)
            var = tk.StringVar()
            self.config_vars[key] = var
            widget: ttk.Widget
            if key == "language":
                widget = ttk.Combobox(
                    grid, textvariable=var, values=("ZH", "EN"), state="readonly"
                )
            else:
                widget = ttk.Entry(grid, textvariable=var)
            widget.grid(row=row, column=col + 1, sticky=tk.EW, padx=(8, 20), pady=6)
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        clash = ttk.LabelFrame(tab, text="Clash 自动切换", padding=12)
        clash.pack(fill=tk.X, pady=(14, 0))
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
            ttk.Label(clash, text=title).grid(row=row, column=col, sticky=tk.W, pady=6)
            var = tk.StringVar()
            self.clash_vars[key] = var
            if key == "enabled":
                widget = ttk.Combobox(
                    clash, textvariable=var, values=("true", "false"), state="readonly"
                )
            else:
                widget = ttk.Entry(clash, textvariable=var, show="*" if key == "secret" else "")
            widget.grid(row=row, column=col + 1, sticky=tk.EW, padx=(8, 20), pady=6)
        clash.columnconfigure(1, weight=1)
        clash.columnconfigure(3, weight=1)

        ttk.Label(
            tab,
            text="复杂的 chat / media_types / file_formats 仍建议直接编辑 config.yaml。",
        ).pack(anchor=tk.W, pady=(14, 0))

    def _build_log_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="运行日志")
        self.log_text = tk.Text(tab, wrap=tk.WORD)
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
        self.metric_vars["bot"].set("启用" if snapshot["bot_enabled"] else "未启用")
        self.metric_vars["clash"].set("启用" if snapshot["clash_enabled"] else "关闭")
        self.state_label.configure(
            text="下载中" if snapshot["download_state"] == "downloading" else "已暂停"
        )
        self.pause_button.configure(
            text="暂停下载" if snapshot["download_state"] == "downloading" else "继续下载"
        )

    def _refresh_downloads(self):
        self._replace_tree_rows(
            self.download_tree,
            [
                (
                    row["task_id"],
                    row["chat_id"],
                    row["message_id"],
                    row["file_name"],
                    row["progress"],
                    f"{row['downloaded']} / {row['total']}",
                    row["speed"],
                    row["status"],
                    row["path"],
                )
                for row in collect_download_rows()
            ],
        )

    def _refresh_tasks(self):
        rows = collect_task_rows(self.app)
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

    def close(self):
        if messagebox.askokcancel("退出", "确定要退出下载器吗？"):
            self.app.is_running = False
            self.root.after(300, self.root.destroy)


def run_native_ui(core_module):
    """Run the native desktop UI."""
    NativeDownloaderUI(core_module).start()
