import unittest
from types import SimpleNamespace

from module.download_limits import allowed_media, validate_limits


class DownloadLimitsTest(unittest.TestCase):
    def test_size_bounds_and_unknown(self):
        limits = {"min_size_mb": 1, "max_size_mb": 2}
        for size, expected in [(1048575, False), (1048576, True), (2097152, True), (2097153, False), (None, False)]:
            self.assertEqual(allowed_media(SimpleNamespace(file_size=size), "document", limits), expected)
        self.assertTrue(allowed_media(SimpleNamespace(), "document", {}))

    def test_resolution_short_side_and_nonvideo(self):
        limits = {"min_video_resolution": 720, "max_video_resolution": 1080}
        for width, height, expected in [(1920, 1080, True), (720, 1280, True), (640, 480, False), (3840, 2160, False), (None, None, False)]:
            media = SimpleNamespace(width=width, height=height)
            self.assertEqual(allowed_media(media, "video", limits), expected)
        self.assertTrue(allowed_media(SimpleNamespace(), "photo", limits))
        self.assertTrue(allowed_media(SimpleNamespace(length=720), "video_note", limits))

    def test_invalid_config(self):
        for limits in (None, {"min_size_mb": -1}, {"max_size_mb": "5"}, {"min_size_mb": 2, "max_size_mb": 1}):
            with self.assertRaises(ValueError):
                validate_limits(limits)
