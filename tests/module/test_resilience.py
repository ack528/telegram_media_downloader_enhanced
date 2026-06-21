import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from module.app import DownloadStatus, TaskNode
import module.download_stat as download_stat
from module.pyrogram_extension import (
    fetch_message,
    record_download_status,
    reset_download_cache,
)


class FetchClient:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    async def get_messages(self, chat_id, message_ids):
        self.calls += 1
        if self.calls <= self.failures:
            raise OSError("Connection lost")
        return SimpleNamespace(id=message_ids, chat=SimpleNamespace(id=chat_id))


class ResilienceTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_download_cache()
        download_stat.reset_download_statistics()

    async def test_fetch_message_retries_connection_loss(self):
        client = FetchClient(failures=2)
        message = SimpleNamespace(id=10, chat=SimpleNamespace(id=20))

        with mock.patch("module.pyrogram_extension.FETCH_MESSAGE_RETRY_DELAY", 0):
            result = await fetch_message(client, message)

        self.assertEqual(result.id, 10)
        self.assertEqual(client.calls, 3)

    async def test_record_download_status_resets_cache_after_exception(self):
        calls = 0

        @record_download_status
        async def flaky_download(client, message, media_types, file_formats, node):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("Connection lost")
            return DownloadStatus.SuccessDownload, "file.mp4"

        node = TaskNode(chat_id="chat")
        message = SimpleNamespace(id=1)

        with self.assertRaises(OSError):
            await flaky_download(None, message, [], {}, node)

        status, file_name = await flaky_download(None, message, [], {}, node)

        self.assertEqual(status, DownloadStatus.SuccessDownload)
        self.assertEqual(file_name, "file.mp4")
        self.assertEqual(calls, 2)

    async def test_download_media_marks_fetch_failure_failed(self):
        from media_downloader import download_media

        node = TaskNode(chat_id=20)
        message = SimpleNamespace(id=99, chat=SimpleNamespace(id=20))

        async def fail_fetch(client, message):
            raise TimeoutError("fetch timeout")

        with mock.patch("media_downloader.fetch_message", fail_fetch):
            status, file_name = await download_media(None, message, ["video"], {}, node)

        self.assertEqual(status, DownloadStatus.FailedDownload)
        self.assertIsNone(file_name)

    async def test_network_failure_request_switches_clash_without_active_download(self):
        import media_downloader

        old_is_running = media_downloader.app.is_running
        old_clash_config = media_downloader.app.clash_config
        media_downloader.app.is_running = True
        media_downloader.app.clash_config = {
            "enabled": True,
            "switch_cooldown_seconds": 0,
        }
        media_downloader._clash_switch_event.clear()
        media_downloader._clash_switch_reason = None

        switch_calls = 0

        async def fake_switch():
            nonlocal switch_calls
            switch_calls += 1
            media_downloader.app.is_running = False
            return SimpleNamespace(selector="Proxy", node="US Node", delay=10)

        try:
            with mock.patch("media_downloader.LOW_SPEED_MONITOR_INTERVAL", 0.01):
                with mock.patch("media_downloader._switch_clash_node", fake_switch):
                    with mock.patch("media_downloader.get_active_download_count", return_value=0):
                        with mock.patch("media_downloader.get_total_download_speed", return_value=0):
                            task = asyncio.create_task(
                                media_downloader.monitor_low_download_speed()
                            )
                            media_downloader.request_clash_switch("fetch failed")
                            await asyncio.wait_for(task, timeout=1)
        finally:
            media_downloader._clash_switch_event.clear()
            media_downloader._clash_switch_reason = None
            media_downloader.app.clash_config = old_clash_config
            media_downloader.app.is_running = old_is_running

        self.assertEqual(switch_calls, 1)

    async def test_single_fetch_failure_does_not_switch_clash_when_downloads_are_healthy(self):
        import media_downloader

        old_clash_config = media_downloader.app.clash_config
        media_downloader.app.clash_config = {
            "enabled": True,
            "low_speed_kb": 100,
        }
        media_downloader._clash_switch_event.clear()
        media_downloader._clash_switch_reason = None

        try:
            with mock.patch("media_downloader.get_active_download_count", return_value=4):
                with mock.patch("media_downloader.get_total_download_speed", return_value=2 * 1024 * 1024):
                    media_downloader.request_clash_switch("message 1709 fetch failed")
        finally:
            media_downloader.app.clash_config = old_clash_config

        self.assertFalse(media_downloader._clash_switch_event.is_set())
        self.assertIsNone(media_downloader._clash_switch_reason)

    async def test_stale_speed_does_not_block_clash_switch_request(self):
        import media_downloader

        old_clash_config = media_downloader.app.clash_config
        media_downloader.app.clash_config = {
            "enabled": True,
            "low_speed_kb": 100,
        }
        media_downloader._clash_switch_event.clear()
        media_downloader._clash_switch_reason = None
        download_stat._download_result = {
            "chat": {
                1: {
                    "down_byte": 10,
                    "total_size": 100,
                    "download_speed": 4 * 1024 * 1024,
                    "end_time": time.time() - download_stat.STALE_SPEED_SECONDS - 1,
                }
            }
        }
        download_stat._total_download_speed = 4 * 1024 * 1024
        download_stat._last_download_time = (
            time.time() - download_stat.STALE_SPEED_SECONDS - 1
        )

        try:
            media_downloader.request_clash_switch("message 1849 download stalled")
        finally:
            media_downloader.app.clash_config = old_clash_config

        self.assertTrue(media_downloader._clash_switch_event.is_set())
        self.assertEqual(
            media_downloader._clash_switch_reason,
            "message 1849 download stalled",
        )


if __name__ == "__main__":
    unittest.main()
