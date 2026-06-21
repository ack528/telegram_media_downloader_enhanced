import os
import tempfile
import unittest

from module.app import Application
from module.web import get_flask_app
import module.web as web


class WebApiTestCase(unittest.TestCase):
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
        web._runtime_app = self.app
        get_flask_app().config["TESTING"] = True
        get_flask_app().config["LOGIN_DISABLED"] = True
        self.client = get_flask_app().test_client()

    def tearDown(self):
        web._runtime_app = None
        self.temp_dir.cleanup()

    def test_dashboard_returns_runtime_summary(self):
        response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("summary", data)
        self.assertIn("downloads", data)
        self.assertIn("tasks", data)
        self.assertIn("config_preview", data)

    def test_index_renders_modern_dashboard_shell(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("下载控制台", html)
        self.assertIn("api/dashboard", html)
        self.assertIn("configForm", html)

    def test_config_post_updates_public_values(self):
        response = self.client.post(
            "/api/config",
            json={
                "language": "ZH",
                "save_path": os.path.join(self.temp_dir.name, "downloads"),
                "max_download_task": 7,
                "scan_prefetch_limit": 3,
                "clash": {
                    "enabled": True,
                    "controller": "http://127.0.0.1:9097",
                    "low_speed_kb": 128,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["config"]["max_download_task"], 7)
        self.assertEqual(data["config"]["scan_prefetch_limit"], 3)
        self.assertEqual(data["config"]["clash"]["low_speed_kb"], 128)
        self.assertTrue(os.path.exists(self.app.config_file))


if __name__ == "__main__":
    unittest.main()
