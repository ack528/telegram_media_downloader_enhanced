import unittest

from module.download_stat import get_download_result
from module.web import get_flask_app


class WebApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = get_flask_app()
        self.old_login_disabled = self.app.config.get("LOGIN_DISABLED")
        self.app.config["LOGIN_DISABLED"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        get_download_result().clear()
        self.app.config["LOGIN_DISABLED"] = self.old_login_disabled

    def test_download_list_returns_valid_json_for_quoted_filename(self):
        get_download_result()["chat"] = {
            1: {
                "down_byte": 0,
                "total_size": 0,
                "download_speed": 0,
                "file_name": 'C:\\temp\\a"b.mp4',
            }
        }

        response = self.client.get("/get_download_list?already_down=false")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["filename"], 'a"b.mp4')
        self.assertEqual(payload[0]["download_progress"], "0")


if __name__ == "__main__":
    unittest.main()
