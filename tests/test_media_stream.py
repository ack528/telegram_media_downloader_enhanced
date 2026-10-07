import unittest
from unittest import mock

import media_downloader
from module.fast_download import CdnRedirect


class FakeClient:
    def __init__(self):
        self.get_file_calls = []

    async def get_file(self, file_id, size, limit, offset, progress, progress_args):
        self.get_file_calls.append(offset)
        for index in range(offset, 5):
            yield f"legacy{index}".encode()


def fake_parallel(fail_after=None):
    async def iterate(client, file_id, size, offset, **kwargs):
        iterate.kwargs = kwargs
        for index in range(offset, 5):
            if fail_after is not None and index - offset == fail_after:
                raise CdnRedirect()
            yield f"fast{index}".encode()

    return iterate


async def collect(stream):
    return [chunk async for chunk in stream]


class MediaStreamTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.multiple(
            media_downloader.app, download_threads=4, download_connections=4
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_uses_parallel_downloader_with_configured_limits(self):
        parallel = fake_parallel()
        with mock.patch("media_downloader.iter_file_parallel", parallel):
            chunks = await collect(
                media_downloader._media_stream(FakeClient(), None, 5, 1, None, (), 7)
            )
        self.assertEqual(chunks, [b"fast1", b"fast2", b"fast3", b"fast4"])
        self.assertEqual(parallel.kwargs["threads"], 4)
        self.assertEqual(parallel.kwargs["connections"], 4)
        self.assertEqual(parallel.kwargs["epoch"], 7)

    async def test_cdn_files_continue_with_pyrogram_from_next_part(self):
        client = FakeClient()
        with mock.patch("media_downloader.iter_file_parallel", fake_parallel(fail_after=2)):
            chunks = await collect(
                media_downloader._media_stream(client, None, 5, 0, None, (), 0)
            )
        self.assertEqual(chunks, [b"fast0", b"fast1", b"legacy2", b"legacy3", b"legacy4"])
        self.assertEqual(client.get_file_calls, [2])

    async def test_single_thread_single_connection_uses_pyrogram(self):
        client = FakeClient()
        with mock.patch.multiple(
            media_downloader.app, download_threads=1, download_connections=1
        ), mock.patch("media_downloader.iter_file_parallel") as parallel:
            chunks = await collect(
                media_downloader._media_stream(client, None, 5, 3, None, (), 0)
            )
        parallel.assert_not_called()
        self.assertEqual(chunks, [b"legacy3", b"legacy4"])


if __name__ == "__main__":
    unittest.main()
