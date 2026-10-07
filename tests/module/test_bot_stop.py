import unittest
from types import SimpleNamespace
from unittest import mock

from module.app import ChatDownloadConfig, TaskNode, TaskType
from module.bot import DownloadBot, stop_task


class BotStopTestCase(unittest.TestCase):
    def test_stop_recovered_task_forgets_restart_state(self):
        bot = DownloadBot()
        bot.app = mock.Mock()
        node = TaskNode(chat_id=-100123, task_id=7)
        node.scan_finished = False
        bot.task_node[node.task_id] = node

        bot.stop_task("7")

        self.assertTrue(node.is_stop_transmission)
        self.assertNotIn(7, bot.task_node)
        bot.app.forget_bot_download_task.assert_called_once_with(node)

    def test_download_not_finished_until_scan_completes(self):
        node = TaskNode(chat_id=-100123, task_id=7)
        node.is_running = True
        node.total_task = 1
        node.total_download_task = 1

        self.assertFalse(node.is_finish())
        node.scan_finished = True
        self.assertTrue(node.is_finish())

    def test_shutdown_stop_preserves_restart_state(self):
        bot = DownloadBot()
        bot.app = mock.Mock()
        node = TaskNode(chat_id=-100123, task_id=7)
        bot.task_node[node.task_id] = node

        bot.stop_task("all", forget=False)

        self.assertTrue(node.is_stop_transmission)
        self.assertEqual(bot.task_node, {})
        bot.app.forget_bot_download_task.assert_not_called()


class BotStopCallbackTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_stop_menu_edits_the_user_chat_not_bot_sender(self):
        from module import bot as bot_module

        node = TaskNode(chat_id=-100123, task_id=7)
        node.is_running = True
        node.total_task = 1
        bot_module._bot.task_node = {7: node}
        client = mock.AsyncMock()
        query = SimpleNamespace(
            data="stop_download",
            message=SimpleNamespace(
                id=88,
                chat=SimpleNamespace(id=12345),
                from_user=SimpleNamespace(id=99999),
            ),
        )

        try:
            await stop_task(
                client, query, "stop_download", TaskType.Download
            )
        finally:
            bot_module._bot.task_node = {}

        self.assertEqual(client.edit_message_text.await_args.args[0], 12345)

    async def test_recovery_is_registered_even_if_status_message_fails(self):
        bot = DownloadBot()
        bot.bot = mock.AsyncMock()
        bot.bot.send_message.side_effect = OSError("bot unavailable")
        bot.allowed_user_ids = [12345]
        config = ChatDownloadConfig()

        node = await bot.create_status_node(-100123, config, "recover")

        self.assertIn(node.task_id, bot.task_node)
        self.assertIsNone(node.bot)

    async def test_recovery_status_replies_to_original_download_command(self):
        bot = DownloadBot()
        bot.bot = mock.AsyncMock()
        bot.bot.send_message.return_value = SimpleNamespace(id=456)
        bot.allowed_user_ids = [12345]
        config = ChatDownloadConfig()
        config.bot_command_message_id = 321
        config.bot_command_message = "/download https://t.me/test 1 10"

        node = await bot.create_status_node(-100123, config, "recover")

        self.assertEqual(node.reply_message_id, 456)
        self.assertEqual(
            bot.bot.send_message.await_args.kwargs["reply_to_message_id"],
            321,
        )

    async def test_deleted_original_command_falls_back_to_saved_text(self):
        bot = DownloadBot()
        bot.bot = mock.AsyncMock()
        bot.bot.send_message.side_effect = [
            OSError("reply message not found"),
            SimpleNamespace(id=456),
        ]
        bot.allowed_user_ids = [12345]
        config = ChatDownloadConfig()
        config.bot_command_message_id = 321
        config.bot_command_message = "/download https://t.me/test 1 10"

        node = await bot.create_status_node(-100123, config, "recover")

        self.assertEqual(node.reply_message_id, 456)
        fallback_text = bot.bot.send_message.await_args_list[1].args[1]
        self.assertIn("/download https://t.me/test 1 10", fallback_text)
        self.assertNotIn(
            "reply_to_message_id",
            bot.bot.send_message.await_args_list[1].kwargs,
        )

    async def test_legacy_status_recovers_original_reply_reference(self):
        bot = DownloadBot()
        bot.bot = mock.AsyncMock()
        bot.bot.get_messages.return_value = SimpleNamespace(
            reply_to_message_id=321
        )
        bot.bot.send_message.return_value = SimpleNamespace(id=456)
        bot.allowed_user_ids = [12345]
        config = ChatDownloadConfig()
        config.bot_reply_message_id = 111

        await bot.create_status_node(-100123, config, "recover")

        self.assertEqual(config.bot_command_message_id, 321)
        self.assertEqual(
            bot.bot.send_message.await_args.kwargs["reply_to_message_id"],
            321,
        )


if __name__ == "__main__":
    unittest.main()
