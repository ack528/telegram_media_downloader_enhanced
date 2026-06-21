import time
import unittest

import module.download_stat as download_stat


class DownloadStatTestCase(unittest.TestCase):
    def tearDown(self):
        download_stat.reset_download_statistics()

    def test_stale_total_speed_is_reset_to_zero(self):
        download_stat._total_download_speed = 1024 * 1024
        download_stat._last_download_time = (
            time.time() - download_stat.STALE_SPEED_SECONDS - 1
        )

        self.assertEqual(download_stat.get_total_download_speed(), 0)

    def test_stale_file_speed_is_reset_to_zero(self):
        download_stat._download_result = {
            "chat": {
                1: {
                    "down_byte": 10,
                    "total_size": 100,
                    "download_speed": 4096,
                    "end_time": time.time() - download_stat.STALE_SPEED_SECONDS - 1,
                }
            }
        }

        result = download_stat.get_download_result()

        self.assertEqual(result["chat"][1]["download_speed"], 0)


if __name__ == "__main__":
    unittest.main()
