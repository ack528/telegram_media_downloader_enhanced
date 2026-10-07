import unittest
from unittest import mock

from module import download_stat
from module.download_stat import (
    finish_download_status,
    get_download_result,
    remove_download_status,
)


class DownloadStatTestCase(unittest.TestCase):
    def tearDown(self):
        get_download_result().clear()

    def test_success_is_retained_for_web_history(self):
        get_download_result()["chat"] = {
            1: {
                "down_byte": 5,
                "total_size": 10,
                "download_speed": 2,
            }
        }

        finish_download_status("chat", 1, succeeded=True)

        result = get_download_result()["chat"][1]
        self.assertEqual(result["down_byte"], 10)
        self.assertEqual(result["download_speed"], 0)
        self.assertTrue(result["terminal"])

    def test_failed_progress_is_removed(self):
        get_download_result()["chat"] = {
            1: {
                "down_byte": 5,
                "total_size": 10,
                "download_speed": 2,
            }
        }

        finish_download_status("chat", 1, succeeded=False)

        self.assertNotIn("chat", get_download_result())

    def test_total_speed_decays_when_no_progress_arrives(self):
        with (
            mock.patch.object(download_stat, "_total_download_speed", 1234),
            mock.patch.object(download_stat, "_last_download_time", 10),
            mock.patch("module.download_stat.time.time", return_value=20),
        ):
            self.assertEqual(download_stat.get_total_download_speed(), 0)


if __name__ == "__main__":
    unittest.main()
