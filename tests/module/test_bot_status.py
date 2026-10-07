import asyncio
import unittest
from unittest import mock

import pyrogram

from module.app import TaskNode
from module.pyrogram_extension import (
    _edit_bot_status_message,
    report_bot_status,
    set_status_clash_config,
)
from module.download_stat import get_download_result


class FakeBotClient:
    def __init__(self, delay=0):
        self.delay = delay
        self.messages = []

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.messages.append((chat_id, message_id, text, kwargs))
        return True


class RejectHtmlBotClient(FakeBotClient):
    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        if kwargs.get("parse_mode") is pyrogram.enums.ParseMode.HTML:
            raise pyrogram.errors.exceptions.bad_request_400.BadRequest(
                "ENTITY_BOUNDS_INVALID"
            )
        return await super().edit_message_text(chat_id, message_id, text, **kwargs)


class BotStatusTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_html_falls_back_to_plain_text(self):
        client = RejectHtmlBotClient()
        node = TaskNode(
            chat_id="chat", from_user_id=1, reply_message_id=2, bot=True, task_id=3
        )

        updated = await _edit_bot_status_message(
            client, node, "<b>下载任务 #3</b> a &lt;b&gt;", use_html=True
        )

        self.assertTrue(updated)
        self.assertEqual(client.messages[0][2], "下载任务 #3 a <b>")
        self.assertIs(
            client.messages[0][3]["parse_mode"], pyrogram.enums.ParseMode.DISABLED
        )

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
        self.assertIs(
            client.messages[0][3]["parse_mode"],
            pyrogram.enums.ParseMode.HTML,
        )
        self.assertIn("\u4efb\u52a1 #1", node.last_edit_msg)
        self.assertIn("\u66f4\u65b0</i>", node.last_edit_msg)
        self.assertIn("\u26a1", node.last_edit_msg)

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

    async def test_status_is_bounded_by_telegram_utf16_limit(self):
        client = FakeBotClient()
        node = TaskNode(
            chat_id="chat",
            from_user_id=123,
            reply_message_id=456,
            bot=True,
            task_id=1,
        )

        updated = await _edit_bot_status_message(client, node, "😀" * 3000)

        self.assertTrue(updated)
        sent_text = client.messages[0][2]
        self.assertLessEqual(len(sent_text.encode("utf-16-le")) // 2, 4000)
        self.assertTrue(sent_text.endswith("…"))

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

    async def test_status_shows_only_five_most_recent_active_downloads(self):
        client = FakeBotClient()
        node = TaskNode(
            chat_id="chat",
            from_user_id=123,
            reply_message_id=456,
            bot=True,
            task_id=7,
        )
        messages = {}
        for message_id in range(1, 8):
            messages[message_id] = {
                "task_id": 7,
                "down_byte": 10,
                "total_size": 100,
                "file_name": f"{message_id}.mp4",
                "download_speed": 1,
                "end_time": message_id,
            }
        get_download_result()["chat"] = messages

        try:
            await report_bot_status(client, node, immediate_reply=True)
        finally:
            get_download_result().clear()

        text = client.messages[0][2]
        self.assertNotIn("1.mp4", text)
        self.assertNotIn("2.mp4", text)
        for message_id in range(3, 8):
            self.assertIn(f"{message_id}.mp4", text)


if __name__ == "__main__":
    unittest.main()

