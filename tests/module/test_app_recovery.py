"""Tests for download recovery state."""
import unittest

from module.app import Application, ChatDownloadConfig, DownloadStatus, TaskNode


class TestDownloadRecoveryState(unittest.TestCase):
    def test_pending_download_is_removed_when_finished(self):
        app = Application("config.yaml", "data.yaml")
        node = TaskNode(chat_id="chat")
        app.chat_download_config["chat"] = ChatDownloadConfig()

        app.mark_download_pending(node, 123)

        download_config = app.chat_download_config["chat"]
        self.assertEqual(download_config.ids_to_retry, [123])
        self.assertTrue(download_config.ids_to_retry_dict[123])

        app.mark_download_finished(node, 123, DownloadStatus.SuccessDownload)

        self.assertEqual(download_config.ids_to_retry, [])
        self.assertNotIn(123, download_config.ids_to_retry_dict)

    def test_failed_download_stays_pending(self):
        app = Application("config.yaml", "data.yaml")
        node = TaskNode(chat_id="chat")
        app.chat_download_config["chat"] = ChatDownloadConfig()

        app.mark_download_pending(node, 123)
        app.mark_download_finished(node, 123, DownloadStatus.FailedDownload)

        download_config = app.chat_download_config["chat"]
        self.assertEqual(download_config.ids_to_retry, [123])
        self.assertTrue(download_config.ids_to_retry_dict[123])
