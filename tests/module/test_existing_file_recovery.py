import os
import tempfile
import unittest

from media_downloader import _recover_existing_download, _temp_download_path
from module.app import DownloadStatus


def write_bytes(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)


class ExistingFileRecoveryTestCase(unittest.TestCase):
    def test_existing_complete_file_skips_and_removes_stale_temps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = os.path.join(temp_dir, "downloads", "file.mp4")
            temp_path = os.path.join(temp_dir, "temp", "file.mp4")
            resume_path = _temp_download_path(temp_path)
            write_bytes(final_path, 10)
            write_bytes(temp_path, 3)
            write_bytes(resume_path, 4)

            status = _recover_existing_download(final_path, temp_path, 10, final_path)

            self.assertEqual(status, DownloadStatus.SkipDownload)
            self.assertTrue(os.path.exists(final_path))
            self.assertFalse(os.path.exists(temp_path))
            self.assertFalse(os.path.exists(resume_path))

    def test_partial_final_does_not_overwrite_larger_resume_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = os.path.join(temp_dir, "downloads", "file.mp4")
            temp_path = os.path.join(temp_dir, "temp", "file.mp4")
            resume_path = _temp_download_path(temp_path)
            write_bytes(final_path, 4)
            write_bytes(resume_path, 8)

            status = _recover_existing_download(final_path, temp_path, 10, final_path)

            self.assertIsNone(status)
            self.assertFalse(os.path.exists(final_path))
            self.assertTrue(os.path.exists(resume_path))
            self.assertEqual(os.path.getsize(resume_path), 8)


if __name__ == "__main__":
    unittest.main()
