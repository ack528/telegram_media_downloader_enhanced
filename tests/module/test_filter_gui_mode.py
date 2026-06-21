import unittest
import subprocess
import sys
from unittest import mock

from module.filter import BaseFilter


class FilterGuiModeTestCase(unittest.TestCase):
    def test_parser_builds_when_standard_streams_are_none(self):
        with mock.patch("sys.stderr", None):
            parser = BaseFilter()

        self.assertIsNotNone(parser.yacc)

    def test_media_downloader_imports_when_standard_error_is_none(self):
        code = (
            "import sys;"
            "sys.stderr=None;"
            "import media_downloader;"
            "assert media_downloader.app is not None"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_media_downloader_imports_when_standard_error_has_no_fileno(self):
        code = (
            "import sys\n"
            "class NoFileno:\n"
            "    def write(self, value): pass\n"
            "    def flush(self): pass\n"
            "sys.stderr=NoFileno()\n"
            "import media_downloader\n"
            "assert media_downloader.app is not None\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
