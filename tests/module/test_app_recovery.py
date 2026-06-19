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

    def test_bot_task_is_loaded_even_when_not_in_config_chat(self):
        app = Application("config.yaml", "data.yaml")

        app.assign_app_data(
            {
                "chat": [
                    {
                        "chat_id": -100123,
                        "ids_to_retry": [10, 11],
                        "bot_task": True,
                        "bot_from_user_id": 99,
                        "download_filter": "video",
                    }
                ]
            }
        )

        download_config = app.chat_download_config[-100123]
        self.assertTrue(download_config.is_bot_task)
        self.assertTrue(download_config.recover_only)
        self.assertEqual(download_config.bot_from_user_id, 99)
        self.assertEqual(download_config.ids_to_retry, [10, 11])
        self.assertTrue(download_config.ids_to_retry_dict[10])

    def test_update_config_handles_bot_task_without_config_chat(self):
        app = Application("config.yaml", "data.yaml")
        app.config = {"chat": []}
        app.app_data = {}
        node = TaskNode(chat_id=-100456, from_user_id=99, reply_message_id=77)
        download_config = ChatDownloadConfig()
        download_config.is_bot_task = True
        download_config.recover_only = True
        download_config.bot_from_user_id = 99
        download_config.node = node
        app.chat_download_config[-100456] = download_config

        app.mark_download_pending(node, 42)
        app.update_config(False)

        self.assertEqual(app.app_data["chat"][0]["chat_id"], -100456)
        self.assertTrue(app.app_data["chat"][0]["bot_task"])
        self.assertEqual(app.app_data["chat"][0]["ids_to_retry"], [42])
