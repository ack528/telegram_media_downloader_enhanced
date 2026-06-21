import os
import asyncio
import tempfile
import threading
import unittest

from module.app import Application
from module.app import ChatDownloadConfig
from module.native_ui import (
    apply_config_changes,
    bind_core_event_loop,
    collect_dashboard_snapshot,
    delete_task,
)


class NativeUiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Application("config.yaml", "data.yaml", "test")
        self.app.config_file = os.path.join(self.temp_dir.name, "config.yaml")
        self.app.app_data_file = os.path.join(self.temp_dir.name, "data.yaml")
        self.app.config = {
            "api_id": "1",
            "api_hash": "hash",
            "bot_token": "token",
            "media_types": ["video"],
            "file_formats": {"video": ["all"]},
            "chat": [{"chat_id": "chat", "last_read_message_id": 1}],
            "clash": dict(self.app.clash_config),
        }
        self.app.app_data = {}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_collect_dashboard_snapshot(self):
        snapshot = collect_dashboard_snapshot(self.app)

        self.assertIn("speed", snapshot)
        self.assertIn("active_count", snapshot)
        self.assertEqual(snapshot["task_count"], 0)

    def test_apply_config_changes_persists_common_values(self):
        restart_required = apply_config_changes(
            self.app,
            {
                "language": "ZH",
                "save_path": os.path.join(self.temp_dir.name, "downloads"),
                "max_download_task": "8",
                "scan_prefetch_limit": "4",
                "clash": {
                    "enabled": True,
                    "controller": "http://127.0.0.1:9097",
                    "low_speed_kb": "150",
                },
            },
        )

        self.assertIn("max_download_task", restart_required)
        self.assertEqual(self.app.max_download_task, 8)
        self.assertEqual(self.app.scan_prefetch_limit, 4)
        self.assertEqual(self.app.clash_config["low_speed_kb"], 150)
        self.assertTrue(os.path.exists(self.app.config_file))

        with open(self.app.config_file, encoding="utf-8") as config_file:
            saved = config_file.read()
        self.assertIn("api_id", saved)
        self.assertIn("bot_token", saved)
        self.assertIn("media_types", saved)

    def test_bind_core_event_loop_in_worker_thread(self):
        class Core:
            app = self.app

        result = []

        def worker():
            bind_core_event_loop(Core)
            result.append(asyncio.get_event_loop() is self.app.loop)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertEqual(result, [True])

    def test_apply_config_changes_rejects_before_config_is_loaded(self):
        self.app.config = {}

        with self.assertRaises(ValueError):
            apply_config_changes(self.app, {"save_path": self.temp_dir.name})

    def test_delete_task_removes_runtime_and_recovery_data(self):
        config = ChatDownloadConfig()
        config.ids_to_retry = [10]
        self.app.chat_download_config["chat"] = config
        self.app.app_data = {"chat": [{"chat_id": "chat", "ids_to_retry": [10]}]}

        self.assertTrue(delete_task(self.app, "chat"))
        self.assertNotIn("chat", self.app.chat_download_config)
        self.assertEqual(self.app.app_data["chat"], [])
        self.assertEqual(self.app.config["chat"], [])


if __name__ == "__main__":
    unittest.main()
