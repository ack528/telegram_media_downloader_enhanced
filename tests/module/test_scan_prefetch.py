import asyncio
import unittest

from media_downloader import app, wait_for_scan_prefetch_window
from module.app import ChatDownloadConfig, TaskNode


class ScanPrefetchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_scan_waits_until_download_window_has_room(self):
        original_limit = app.scan_prefetch_limit
        original_running = app.is_running
        app.scan_prefetch_limit = 1
        app.is_running = True

        config = ChatDownloadConfig()
        node = TaskNode(chat_id="chat", task_id=1)
        node.total_task = 1
        config.finish_task = 0

        wait_task = asyncio.create_task(wait_for_scan_prefetch_window(config, node))
        await asyncio.sleep(0.05)
        self.assertFalse(wait_task.done())

        config.finish_task = 1
        await asyncio.wait_for(wait_task, timeout=2)

        app.scan_prefetch_limit = original_limit
        app.is_running = original_running


if __name__ == "__main__":
    unittest.main()
