import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from flask import Flask

from module import bot as bot_module
from module.app import ChatDownloadConfig, DownloadStatus, TaskNode
from module.desktop import (
    TOKEN_HEADER,
    DesktopApiError,
    DesktopRuntime,
    DownloadHistory,
    register_desktop_api,
)


def _message(message_id=10, title="Test Channel", media="video"):
    return SimpleNamespace(
        id=message_id,
        chat=SimpleNamespace(title=title, first_name=None, username=None),
        media=SimpleNamespace(value=media),
    )


def _runtime(history=None):
    app = mock.Mock()
    app.chat_download_config = {}
    app.clash_config = {"enabled": False}
    app.bot_token = ""
    app.save_path = "D:/downloads"
    app.max_download_task = 5
    history = history or DownloadHistory(tempfile.mkdtemp(), enabled=False)
    return DesktopRuntime(app, history, lambda: 3, mock.AsyncMock())


class DownloadHistoryTestCase(unittest.TestCase):
    def test_records_success_to_monthly_jsonl(self):
        with tempfile.TemporaryDirectory() as base:
            history = DownloadHistory(base)
            node = TaskNode(chat_id=-100123, task_id=4)

            entry = history.record(
                node, _message(), DownloadStatus.SuccessDownload,
                "D:/downloads/a.mp4", 2048, 0,
            )

            self.assertEqual(entry["status"], "success")
            self.assertEqual(entry["chat"], "Test Channel")
            self.assertEqual(entry["type"], "video")
            with open(history.file_path(), encoding="utf-8") as history_file:
                lines = [json.loads(line) for line in history_file]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["size"], 2048)
            self.assertEqual(history.counters["success"], 1)
            self.assertEqual(history.counters["bytes"], 2048)

    def test_ignores_duplicate_in_flight_status(self):
        with tempfile.TemporaryDirectory() as base:
            history = DownloadHistory(base)
            node = TaskNode(chat_id=-100123)

            entry = history.record(
                node, _message(), DownloadStatus.Downloading, None, 0, 0
            )

            self.assertIsNone(entry)
            self.assertFalse(os.path.exists(history.file_path()))

    def test_masks_hidden_file_names(self):
        history = DownloadHistory(tempfile.mkdtemp(), enabled=False)
        entry = history.record(
            TaskNode(chat_id=1), _message(), DownloadStatus.SkipDownload,
            "secret name.mkv", 0, 0, hide_file_name=True,
        )
        self.assertEqual(entry["file"], "****.mkv")
        self.assertEqual(history.counters["skipped"], 1)


class DesktopRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self._saved_nodes = bot_module._bot.task_node
        bot_module._bot.task_node = {}

    def tearDown(self):
        bot_module._bot.task_node = self._saved_nodes

    def test_config_tasks_use_chat_key_and_finished_tasks_move_to_recent(self):
        runtime = _runtime()
        node = TaskNode(chat_id=-100555)
        node.is_running = True
        chat_config = ChatDownloadConfig()
        chat_config.node = node
        chat_config.ids_to_retry = [1, 2]
        runtime.app.chat_download_config[-100555] = chat_config

        snapshot = runtime.task_snapshot()
        self.assertEqual(snapshot["active"][0]["key"], "chat:-100555")
        self.assertEqual(snapshot["active"][0]["pending"], 2)
        self.assertEqual(snapshot["active"][0]["source"], "config")

        runtime.app.chat_download_config.clear()
        snapshot = runtime.task_snapshot()
        self.assertEqual(snapshot["active"], [])
        self.assertTrue(snapshot["recent"][0]["finished"])

    def test_stop_task_by_chat_key(self):
        runtime = _runtime()
        node = TaskNode(chat_id=-100555)
        chat_config = ChatDownloadConfig()
        chat_config.node = node
        runtime.app.chat_download_config[-100555] = chat_config

        self.assertTrue(runtime.stop_task("chat:-100555"))
        self.assertTrue(node.is_stop_transmission)
        self.assertFalse(runtime.stop_task("chat:1"))


class DesktopCreateTaskTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_task_before_login(self):
        runtime = _runtime()
        with self.assertRaises(DesktopApiError):
            await runtime.create_task("https://t.me/example 1 0")

    async def test_rejects_reversed_range(self):
        runtime = _runtime()
        runtime.ready = True
        runtime.client = mock.AsyncMock()
        runtime.client.get_chat.return_value = SimpleNamespace(
            id=-100777, title="Example"
        )
        with mock.patch(
            "module.desktop.parse_link",
            mock.AsyncMock(return_value=("example", None, None)),
        ):
            with self.assertRaises(DesktopApiError):
                await runtime.create_task("https://t.me/example", 10, 5)


class DesktopApiTestCase(unittest.TestCase):
    def setUp(self):
        self.runtime = _runtime()
        flask_app = Flask(__name__)
        register_desktop_api(flask_app, self.runtime, "secret-token")
        self.client = flask_app.test_client()

    def test_rejects_missing_token(self):
        self.assertEqual(self.client.get("/api/desktop/status").status_code, 401)

    def test_status_and_pause_resume(self):
        headers = {TOKEN_HEADER: "secret-token"}
        status = self.client.get("/api/desktop/status", headers=headers).get_json()
        self.assertEqual(status["queue"], 3)
        self.assertFalse(status["paused"])

        self.client.post("/api/desktop/pause", headers=headers)
        status = self.client.get("/api/desktop/status", headers=headers).get_json()
        self.assertTrue(status["paused"])

        self.client.post("/api/desktop/resume", headers=headers)
        status = self.client.get("/api/desktop/status", headers=headers).get_json()
        self.assertFalse(status["paused"])

    def test_shutdown_sets_flag(self):
        self.runtime.app.shutdown_requested = False
        response = self.client.post(
            "/api/desktop/shutdown", headers={TOKEN_HEADER: "secret-token"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.runtime.app.shutdown_requested)


if __name__ == "__main__":
    unittest.main()
