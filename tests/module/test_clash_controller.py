import unittest
from unittest import mock

from module.clash_controller import ClashController


class FakeResponse:
    def __init__(self, payload=None, lines=None):
        self.payload = payload or {}
        self.lines = lines

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_lines(self, chunk_size=1, decode_unicode=True):
        if self.lines is None:
            return iter(())
        return iter(self.lines)


class ClashControllerTestCase(unittest.TestCase):
    def test_disabled_controller_does_nothing(self):
        controller = ClashController({"enabled": False})

        with mock.patch("module.clash_controller.requests.request") as request:
            self.assertIsNone(controller.get_traffic_speed())

        request.assert_not_called()

    def test_get_traffic_speed(self):
        def fake_request(method, url, **kwargs):
            self.assertEqual(method, "GET")
            self.assertTrue(url.endswith("/traffic"))
            self.assertEqual(kwargs["timeout"], 1.5)
            self.assertTrue(kwargs["stream"])
            return FakeResponse(lines=['{"up":1024,"down":2048}'])

        with mock.patch("module.clash_controller.requests.request", fake_request):
            traffic = ClashController(
                {"controller": "127.0.0.1:9097"}
            ).get_traffic_speed()

        self.assertEqual(traffic.up, 1024)
        self.assertEqual(traffic.down, 2048)


if __name__ == "__main__":
    unittest.main()
