import unittest
from unittest import mock

from module.clash_controller import ClashController


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class ClashControllerTestCase(unittest.TestCase):
    def test_switch_to_fast_us_node(self):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "PATCH" and url.endswith("/configs"):
                self.assertEqual(kwargs["json"], {"mode": "rule"})
                return FakeResponse()
            if method == "GET" and url.endswith("/proxies"):
                return FakeResponse(
                    {
                        "proxies": {
                            "Proxy": {
                                "all": [
                                    "HK 01",
                                    "US slow",
                                    "\u7f8e\u56fd fast",
                                ]
                            }
                        }
                    }
                )
            if method == "GET" and "US%20slow" in url:
                return FakeResponse({"delay": 250})
            if method == "GET" and "%E7%BE%8E%E5%9B%BD%20fast" in url:
                return FakeResponse({"delay": 80})
            if method == "PUT" and url.endswith("/proxies/Proxy"):
                self.assertEqual(kwargs["json"], {"name": "\u7f8e\u56fd fast"})
                return FakeResponse()
            self.fail(f"unexpected request: {method} {url}")

        with mock.patch("module.clash_controller.requests.request", fake_request):
            result = ClashController(
                {
                    "controller": "127.0.0.1:9097",
                    "secret": "999",
                    "timeout_ms": 1000,
                }
            ).switch_to_fast_us_node()

        self.assertEqual(result.selector, "Proxy")
        self.assertEqual(result.node, "\u7f8e\u56fd fast")
        self.assertEqual(result.delay, 80)
        self.assertEqual(calls[-1][0], "PUT")

    def test_disabled_controller_does_nothing(self):
        controller = ClashController({"enabled": False})

        with mock.patch("module.clash_controller.requests.request") as request:
            self.assertIsNone(controller.switch_to_fast_us_node())

        request.assert_not_called()

    def test_find_selector_prefers_active_rule_provider_before_global(self):
        controller = ClashController({})
        selector, candidates = controller._find_selector(
            {
                "GLOBAL": {"all": ["DIRECT", "\u7f8e\u56fd global"]},
                "manual-airport": {"all": ["HK 01", "\u7f8e\u56fd real"]},
                "telegram": {"all": ["manual-airport", "DIRECT"], "now": "manual-airport"},
            }
        )

        self.assertEqual(selector, "manual-airport")
        self.assertEqual(candidates, ["HK 01", "\u7f8e\u56fd real"])

    def test_get_traffic_speed(self):
        def fake_request(method, url, **kwargs):
            self.assertEqual(method, "GET")
            self.assertTrue(url.endswith("/traffic"))
            self.assertEqual(kwargs["timeout"], 1.5)
            return FakeResponse({"up": 1024, "down": 2048})

        with mock.patch("module.clash_controller.requests.request", fake_request):
            traffic = ClashController(
                {"controller": "127.0.0.1:9097"}
            ).get_traffic_speed()

        self.assertEqual(traffic.up, 1024)
        self.assertEqual(traffic.down, 2048)


if __name__ == "__main__":
    unittest.main()
