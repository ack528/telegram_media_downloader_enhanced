"""test app"""

import os
import sys
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
