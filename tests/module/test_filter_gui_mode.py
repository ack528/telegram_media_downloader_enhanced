import unittest
from unittest import mock

from module.filter import BaseFilter


class FilterGuiModeTestCase(unittest.TestCase):
    def test_parser_builds_when_standard_streams_are_none(self):
        with mock.patch("sys.stderr", None):
            parser = BaseFilter()

        self.assertIsNotNone(parser.yacc)


if __name__ == "__main__":
    unittest.main()
