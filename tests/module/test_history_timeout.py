import asyncio
import unittest

from module.get_chat_history_v2 import get_chunk_v2


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


if __name__ == "__main__":
    unittest.main()
