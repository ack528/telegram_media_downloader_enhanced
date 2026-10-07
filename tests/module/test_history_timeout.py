import asyncio
import unittest
from unittest import mock

from module.get_chat_history_v2 import get_chat_history_v2, get_chunk_v2


class HangingHistoryClient:
    async def resolve_peer(self, chat_id):
        return chat_id

    async def invoke(self, *args, **kwargs):
        await asyncio.sleep(1)


class HistoryTimeoutTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_get_chunk_times_out(self):
        with self.assertRaises(asyncio.TimeoutError):
            await get_chunk_v2(
                client=HangingHistoryClient(),
                chat_id="me",
                limit=1,
                request_timeout=0.01,
                retry_count=1,
            )

    async def test_empty_raw_page_does_not_fallback_to_unrelated_history(self):
        client = mock.Mock()
        client.get_chat_history = mock.Mock()

        with mock.patch(
            "module.get_chat_history_v2.get_chunk_v2",
            mock.AsyncMock(return_value=[]),
        ):
            result = [
                item
                async for item in get_chat_history_v2(
                    client, "chat", offset_id=9000, reverse=True
                )
            ]

        self.assertEqual(result, [])
        client.get_chat_history.assert_not_called()

    async def test_protocol_parse_failure_is_retried(self):
        client = mock.Mock()
        client.resolve_peer = mock.AsyncMock(return_value="peer")
        client.invoke = mock.AsyncMock(return_value=object())

        with (
            mock.patch(
                "module.get_chat_history_v2.utils.parse_messages",
                mock.AsyncMock(
                    side_effect=[
                        AttributeError(
                            "'BadMsgNotification' object has no attribute 'users'"
                        ),
                        [],
                    ]
                ),
            ),
            mock.patch(
                "module.get_chat_history_v2.asyncio.sleep",
                mock.AsyncMock(),
            ),
        ):
            result = await get_chunk_v2(
                client=client,
                chat_id="chat",
                limit=1,
                retry_count=2,
            )

        self.assertEqual(result, [])
        self.assertEqual(client.invoke.await_count, 2)


if __name__ == "__main__":
    unittest.main()
