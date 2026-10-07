"""test app"""

import os
import sys
import tempfile
import unittest
from unittest import mock

import module.app
from module.app import Application, ChatDownloadConfig, DownloadStatus

sys.path.append("..")  # Adds higher directory to python modules path.


class AppTestCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        config_test = os.path.join(os.path.abspath("."), "config_test.yaml")
        data_test = os.path.join(os.path.abspath("."), "data_test.yaml")
        if os.path.exists(config_test):
            os.remove(config_test)
        if os.path.exists(data_test):
            os.remove(data_test)

    def test_app(self):
        app = Application("", "")
        self.assertEqual(app.save_path, os.path.join(os.path.abspath("."), "downloads"))
        self.assertEqual(app.proxy, {})
        self.assertEqual(app.restart_program, False)

        app.chat_download_config[123] = ChatDownloadConfig()
        app.chat_download_config[123].last_read_message_id = 13
        app.chat_download_config[123].node.download_status[
            6
        ] = DownloadStatus.Downloading
        app.chat_download_config[123].ids_to_retry.append(7)
        # download success
        app.chat_download_config[123].node.download_status[
            8
        ] = DownloadStatus.SuccessDownload
        app.chat_download_config[123].finish_task += 1
        # download success
        app.chat_download_config[123].node.download_status[
            10
        ] = DownloadStatus.SuccessDownload
        app.chat_download_config[123].finish_task += 1
        # not exist message
        app.chat_download_config[123].node.download_status[
            13
        ] = DownloadStatus.SuccessDownload
        app.config["chat"] = [{"chat_id": 123, "last_read_message_id": 5}]

        app.update_config(False)

        self.assertEqual(
            app.chat_download_config[123].last_read_message_id + 1,
            app.config["chat"][0]["last_read_message_id"],
        )
        self.assertEqual(
            [6, 7],
            app.app_data["chat"][0]["ids_to_retry"],
        )

    @mock.patch("module.app._write_yaml_atomic")
    def test_update_config(self, mock_write_yaml):
        app = Application("", "")
        app.config_file = "config_test.yaml"
        app.app_data_file = "data_test.yaml"
        app.config["chat"] = [{"chat_id": 123, "last_read_message_id": 0}]
        app.update_config()
        mock_write_yaml.assert_any_call("config_test.yaml", app.config)
        mock_write_yaml.assert_any_call("data_test.yaml", app.app_data)

    @mock.patch("module.app.time.sleep")
    def test_atomic_yaml_write_retries_access_denied(self, mock_sleep):
        original_replace = os.replace
        replace_calls = 0

        def deny_once(source, target):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 1:
                raise PermissionError(5, "Access is denied", target)
            original_replace(source, target)

        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_path = os.path.join(temp_dir, "config.yaml")
            with mock.patch("module.app.os.replace", side_effect=deny_once):
                module.app._write_yaml_atomic(yaml_path, {"chat": []})

            self.assertTrue(os.path.exists(yaml_path))
            self.assertEqual(replace_calls, 2)
            mock_sleep.assert_called_once_with(0.05)
            self.assertEqual(
                [item for item in os.listdir(temp_dir) if item.endswith(".tmp")],
                [],
            )
