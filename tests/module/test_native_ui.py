import os
import tempfile
import unittest

from module.app import Application
from module.native_ui import apply_config_changes, collect_dashboard_snapshot


class NativeUiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Application("config.yaml", "data.yaml", "test")
        self.app.config_file = os.path.join(self.temp_dir.name, "config.yaml")
        self.app.app_data_file = os.path.join(self.temp_dir.name, "data.yaml")
        self.app.config = {
            "api_id": "1",
            "api_hash": "hash",
            "media_types": ["video"],
            "file_formats": {"video": ["all"]},
            "chat": [],
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


if __name__ == "__main__":
    unittest.main()
