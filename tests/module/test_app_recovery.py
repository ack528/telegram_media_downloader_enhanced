"""Tests for download recovery state."""
import os
import tempfile
import unittest
from unittest import mock

from module.app import Application, ChatDownloadConfig, DownloadStatus, TaskNode


class TestDownloadRecoveryState(unittest.TestCase):
    def test_update_config_serializes_pyrogram_string_subclasses(self):
        class PyrogramText(str):
            """Approximate the special string type used by Pyrogram."""

        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.yaml")
            data_file = os.path.join(temp_dir, "data.yaml")
            app = Application(config_file, data_file)
            app.config = {"chat": []}
            app.app_data = {}
            node = TaskNode(chat_id=-100456)
            download_config = ChatDownloadConfig()
            download_config.is_bot_task = True
            download_config.node = node
            download_config.bot_command_message = PyrogramText(
                "/download https://t.me/COSAVMY 1 9200"
            )
            download_config.bot_reply_message = PyrogramText("downloading")
            download_config.download_filter = PyrogramText("video")
            app.chat_download_config[node.chat_id] = download_config

            app.update_config(True)

            persisted = app.app_data["chat"][0]
            self.assertIs(type(persisted["bot_command_message"]), str)
            self.assertIs(type(persisted["bot_reply_message"]), str)
            self.assertIs(type(persisted["download_filter"]), str)
            self.assertTrue(os.path.exists(data_file))

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
                        "bot_command_message_id": 55,
                        "bot_command_message": "/download https://t.me/test 1 10",
                        "download_filter": "video",
                    }
                ]
            }
        )

        download_config = app.chat_download_config[-100123]
        self.assertTrue(download_config.is_bot_task)
        self.assertTrue(download_config.recover_only)
        self.assertEqual(download_config.bot_from_user_id, 99)
        self.assertEqual(download_config.bot_command_message_id, 55)
        self.assertEqual(
            download_config.bot_command_message,
            "/download https://t.me/test 1 10",
        )
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
        download_config.bot_command_message_id = 55
        download_config.bot_command_message = "/download https://t.me/test 1 10"
        download_config.node = node
        app.chat_download_config[-100456] = download_config

        app.mark_download_pending(node, 42)
        app.update_config(False)

        self.assertEqual(app.app_data["chat"][0]["chat_id"], -100456)
        self.assertTrue(app.app_data["chat"][0]["bot_task"])
        self.assertEqual(app.app_data["chat"][0]["ids_to_retry"], [42])
        self.assertEqual(
            app.app_data["chat"][0]["bot_command_message_id"], 55
        )
        self.assertEqual(
            app.app_data["chat"][0]["bot_command_message"],
            "/download https://t.me/test 1 10",
        )

    def test_completed_bot_task_is_not_loaded_for_recovery(self):
        app = Application("config.yaml", "data.yaml")

        app.assign_app_data(
            {
                "chat": [
                    {
                        "chat_id": -100123,
                        "ids_to_retry": [],
                        "bot_task": True,
                        "recover_only": False,
                        "scan_finished": True,
                    }
                ]
            }
        )

        self.assertNotIn(-100123, app.chat_download_config)

    def test_empty_unfinished_scan_is_still_loaded(self):
        app = Application("config.yaml", "data.yaml")

        app.assign_app_data(
            {
                "chat": [
                    {
                        "chat_id": -100123,
                        "ids_to_retry": [],
                        "bot_task": True,
                        "scan_finished": False,
                        "last_read_message_id": 10,
                        "end_offset_id": 100,
                    }
                ]
            }
        )

        self.assertIn(-100123, app.chat_download_config)
        self.assertFalse(app.chat_download_config[-100123].scan_finished)

    def test_finished_scan_with_pending_ids_recovers_ids_only(self):
        app = Application("config.yaml", "data.yaml")

        app.assign_app_data(
            {
                "chat": [
                    {
                        "chat_id": -100123,
                        "ids_to_retry": [42],
                        "bot_task": True,
                        "scan_finished": True,
                    }
                ]
            }
        )

        config = app.chat_download_config[-100123]
        self.assertTrue(config.scan_finished)
        self.assertTrue(config.recover_only)

    def test_forget_bot_task_removes_only_matching_node(self):
        app = Application("config.yaml", "data.yaml")
        app.config = {"chat": []}
        app.app_data = {}
        node = TaskNode(chat_id=-100456, task_id=3)
        download_config = ChatDownloadConfig()
        download_config.is_bot_task = True
        download_config.node = node
        app.chat_download_config[node.chat_id] = download_config
        app.update_config = mock.Mock()

        self.assertTrue(app.forget_bot_download_task(node))
        self.assertNotIn(node.chat_id, app.chat_download_config)
        app.update_config.assert_called_once_with(True)
