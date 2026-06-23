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


if __name__ == "__main__":
    unittest.main()
