import json
import unittest
from types import SimpleNamespace
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


class DownloadSpeedTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        get_download_result().clear()
        download_stat.set_download_state(download_stat.DownloadState.Downloading)
        self.now = 100.0
        self.clock = mock.patch.object(
            download_stat, "monotonic", side_effect=lambda: self.now
        )
        self.clock.start()
        self.node = SimpleNamespace(chat_id="chat", task_id=1, is_stop_transmission=False)
        self.client = mock.Mock()

    def tearDown(self):
        self.clock.stop()
        get_download_result().clear()
        download_stat.set_download_state(download_stat.DownloadState.Downloading)

    async def progress(self, message, done):
        await download_stat.update_download_status(
            done, 1000000000, message, "sample.mp4", 1.0, self.node, self.client
        )

    def rates(self):
        return {
            key: value["download_speed"]
            for key, value in download_stat.get_download_result_snapshot()["chat"].items()
        }

    async def test_staggered_files_sum_to_the_same_total(self):
        await self.progress(1, 0)
        await self.progress(2, 0)
        self.now += 1
        await self.progress(1, 100)
        self.assertEqual(download_stat.get_total_download_speed(), 100)
        self.now += 0.5
        await self.progress(2, 300)
        self.assertEqual(self.rates(), {1: 100, 2: 200})
        self.assertEqual(download_stat.get_total_download_speed(), 300)

    async def test_first_interval_does_not_double_count_initial_chunks(self):
        await self.progress(1, 0)
        self.now += 0.5
        await self.progress(1, 500)
        self.assertEqual(self.rates()[1], 1000)
        self.now += 0.5
        await self.progress(1, 1000)
        self.assertEqual(self.rates()[1], 1000)

    async def test_resume_offset_is_not_download_speed(self):
        await self.progress(1, 100000000)
        self.assertEqual(download_stat.get_total_download_speed(), 0)
        self.now += 1
        await self.progress(1, 100001000)
        self.assertEqual(self.rates()[1], 1000)
        self.assertEqual(download_stat.get_total_download_speed(), 1000)

    async def test_stalled_file_expires_while_another_keeps_downloading(self):
        await self.progress(1, 0)
        await self.progress(2, 0)
        self.now += 1
        await self.progress(1, 100)
        await self.progress(2, 200)
        self.now += 3
        await self.progress(2, 800)
        self.assertEqual(self.rates(), {1: 0, 2: 200})
        self.assertEqual(download_stat.get_total_download_speed(), 200)
        self.now += 3
        self.assertEqual(self.rates(), {1: 0, 2: 0})
        self.assertEqual(download_stat.get_total_download_speed(), 0)

    async def test_completed_and_failed_files_leave_no_phantom_total(self):
        await self.progress(1, 0)
        await self.progress(2, 0)
        self.now += 1
        await self.progress(1, 100)
        await self.progress(2, 200)
        finish_download_status("chat", 1, succeeded=True)
        self.assertEqual(self.rates(), {1: 0, 2: 200})
        self.assertEqual(download_stat.get_total_download_speed(), 200)
        finish_download_status("chat", 2, succeeded=False)
        self.assertEqual(download_stat.get_total_download_speed(), 0)

    async def test_pause_clears_rates_and_resume_excludes_pause_time(self):
        await self.progress(1, 0)
        self.now += 1
        await self.progress(1, 100)
        download_stat.set_download_state(download_stat.DownloadState.StopDownload)
        self.assertEqual(self.rates()[1], 0)
        self.assertEqual(download_stat.get_total_download_speed(), 0)
        self.now += 100
        download_stat.set_download_state(download_stat.DownloadState.Downloading)
        self.now += 1
        await self.progress(1, 200)
        self.assertEqual(self.rates()[1], 100)

    async def test_retry_and_wall_clock_changes_do_not_spike_rates(self):
        await self.progress(1, 10000)
        self.now += 1
        await self.progress(1, 11000)
        await self.progress(1, 10000)  # aligned resume offset after an interruption
        self.assertEqual(self.rates()[1], 0)
        self.now += 1
        with mock.patch("module.download_stat.time.time", return_value=-1000):
            await self.progress(1, 10100)
        self.assertEqual(self.rates()[1], 100)

    async def test_snapshot_does_not_expose_sampling_state(self):
        await self.progress(1, 0)
        snapshot = download_stat.get_download_result_snapshot()
        json.dumps(snapshot)
        self.assertFalse(any(key.startswith("_") for key in snapshot["chat"][1]))


if __name__ == "__main__":
    unittest.main()
