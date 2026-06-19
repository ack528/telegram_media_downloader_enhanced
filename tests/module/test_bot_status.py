import asyncio
import unittest
from unittest import mock

from module.app import TaskNode
from module.pyrogram_extension import (
    _edit_bot_status_message,
    report_bot_status,
    set_status_clash_config,
)


class FakeBotClient:
    def __init__(self, delay=0):
        self.delay = delay
        self.messages = []

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.messages.append((chat_id, message_id, text, kwargs))
        return True


class BotStatusTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_report_bot_status_records_last_edit_after_success(self):
        client = FakeBotClient()
        node = TaskNode(
            chat_id="chat",
            from_user_id=123,
            reply_message_id=456,
            bot=True,
            task_id=1,
        )

        await report_bot_status(client, node, immediate_reply=True)

        self.assertEqual(len(client.messages), 1)
        self.assertEqual(node.last_edit_msg, client.messages[0][2])
        self.assertIn("\u66f4\u65b0\u65f6\u95f4:", node.last_edit_msg)
        self.assertIn("Clash \u4e0b\u8f7d\u901f\u5ea6:", node.last_edit_msg)
        self.assertIn("\u8f6f\u4ef6\u603b\u4e0b\u8f7d\u901f\u5ea6:", node.last_edit_msg)

    async def test_edit_bot_status_timeout_does_not_record_success(self):
        client = FakeBotClient(delay=0.05)
        node = TaskNode(
            chat_id="chat",
            from_user_id=123,
            reply_message_id=456,
            bot=True,
            task_id=1,
        )

        with mock.patch("module.pyrogram_extension.BOT_STATUS_EDIT_TIMEOUT", 0.01):
            updated = await _edit_bot_status_message(client, node, "status")

        self.assertFalse(updated)
        self.assertEqual(client.messages, [])

    async def test_slow_clash_status_query_does_not_block_status_update(self):
        client = FakeBotClient()
        node = TaskNode(
            chat_id="chat",
            from_user_id=123,
            reply_message_id=456,
            bot=True,
            task_id=1,
        )

        def slow_traffic_query(*_args, **_kwargs):
            import time

            time.sleep(2)
            return None

        set_status_clash_config({"enabled": True})
        with (
            mock.patch(
                "module.pyrogram_extension.CLASH_TRAFFIC_STATUS_TIMEOUT", 0.01
            ),
            mock.patch(
                "module.pyrogram_extension.ClashController.get_traffic_speed",
                slow_traffic_query,
            ),
        ):
            await asyncio.wait_for(
                report_bot_status(client, node, immediate_reply=True), timeout=1
            )

        self.assertEqual(len(client.messages), 1)


if __name__ == "__main__":
    unittest.main()

