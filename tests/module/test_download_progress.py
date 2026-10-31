import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import media_downloader


class ResumeProgressTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_resume_baseline_precedes_stream_for_sync_and_async_callbacks(self):
        for progress in (mock.Mock(), mock.AsyncMock()):
            with self.subTest(callback=type(progress).__name__), tempfile.TemporaryDirectory() as base:
                target = os.path.join(base, "sample.mp4")
                offset = media_downloader.DOWNLOAD_CHUNK_SIZE
                partial = media_downloader._temp_download_path(target)
                with open(partial, "wb") as stream:
                    stream.write(b"a" * offset)

                async def chunks(*_args):
                    progress.assert_called_once_with(offset, offset + 3, "marker")
                    yield b"new"

                with (
                    mock.patch("media_downloader.FileId.decode"),
                    mock.patch("media_downloader._media_stream", chunks),
                    mock.patch("media_downloader.get_network_epoch", return_value=0),
                    mock.patch.object(media_downloader.app, "download_stall_timeout", 5),
                ):
                    result = await media_downloader._download_media_with_resume(
                        mock.Mock(), SimpleNamespace(file_id="fake"), target,
                        offset + 3, progress, ("marker",),
                    )

                self.assertEqual(result, target)
                with open(target, "rb") as stream:
                    self.assertEqual(stream.read(), b"a" * offset + b"new")
                if isinstance(progress, mock.AsyncMock):
                    progress.assert_awaited_once()
