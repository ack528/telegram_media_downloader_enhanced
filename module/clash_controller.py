"""Clash external controller helpers."""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from loguru import logger


DEFAULT_US_KEYWORDS = (
    "us",
    "usa",
    "united states",
    "america",
    "\u7f8e\u56fd",
    "\u7f8e\u570b",
    "\u6d1b\u6749\u77f6",
    "\u6d1b\u6749\u78ef",
    "\u5723\u4f55\u585e",
    "\u8056\u4f55\u585e",
    "\u7ebd\u7ea6",
    "\u7d10\u7d04",
    "\U0001f1fa\U0001f1f8",
)


@dataclass
class ClashSwitchResult:
    """Selected Clash node result."""

    selector: str
    node: str
    delay: int


@dataclass
class ClashTraffic:
    """Current Clash traffic speed in bytes per second."""

    up: int
    down: int


class ClashController:
    """Small wrapper for Clash external controller APIs."""

    def __init__(self, config: dict):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.base_url = self._normalize_base_url(
            self.config.get("controller", "http://127.0.0.1:9097")
        )
        self.secret = str(self.config.get("secret", "999"))
        self.selector = self.config.get("selector", "")
        self.timeout_ms = int(self.config.get("timeout_ms", 5000))
        self.test_url = self.config.get(
            "test_url", "https://www.gstatic.com/generate_204"
        )
        self.request_timeout = max(self.timeout_ms / 1000 + 2, 5)
        self.us_keywords = tuple(
            str(keyword).lower()
            for keyword in self.config.get("us_keywords", DEFAULT_US_KEYWORDS)
        )

    @staticmethod
    def _normalize_base_url(controller: str) -> str:
        controller = str(controller or "").strip().rstrip("/")
        if not controller:
            controller = "127.0.0.1:9097"
        if not controller.startswith(("http://", "https://")):
            controller = f"http://{controller}"
        return controller

    @property
    def headers(self) -> Dict[str, str]:
        if not self.secret:
            return {}
        return {"Authorization": f"Bearer {self.secret}"}

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", self.request_timeout)
        return requests.request(
            method,
            url,
            headers=self.headers,
            timeout=timeout,
            **kwargs,
        )

    def _get_proxies(self) -> Dict[str, dict]:
        response = self._request("GET", "/proxies")
        response.raise_for_status()
        return response.json().get("proxies", {})

    def _ensure_rule_mode(self):
        if not bool(self.config.get("force_rule_mode", True)):
            return

        try:
            response = self._request("PATCH", "/configs", json={"mode": "rule"})
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to switch Clash to rule mode: {}", exc)

    def _is_us_node(self, node_name: str) -> bool:
        lower_name = node_name.lower()
        return any(keyword in lower_name for keyword in self.us_keywords)

    def _find_selector(self, proxies: Dict[str, dict]) -> Tuple[Optional[str], List[str]]:
        if self.selector:
            proxy = proxies.get(self.selector)
            if proxy and proxy.get("all"):
                return self.selector, proxy["all"]
            logger.warning("Configured Clash selector not found: {}", self.selector)

        first_manual_selector = self._find_first_manual_selector(proxies)
        if first_manual_selector:
            return first_manual_selector

        us_selectors = {
            name: proxy["all"]
            for name, proxy in proxies.items()
            if proxy.get("all")
            and any(self._is_us_node(node) for node in proxy["all"])
        }

        for name, proxy in proxies.items():
            if name == "GLOBAL" or not proxy.get("all"):
                continue
            now = proxy.get("now")
            if now in us_selectors and now != "GLOBAL":
                return now, us_selectors[now]

        preferred_names = (
            "Proxy",
            "PROXY",
            "\u8282\u70b9\u9009\u62e9",
            "\u7bc0\u9ede\u9078\u64c7",
            "\U0001f680 \u8282\u70b9\u9009\u62e9",
            "\U0001f680 \u7bc0\u9ede\u9078\u64c7",
        )
        for name in preferred_names:
            if name in us_selectors:
                return name, us_selectors[name]

        for name, candidates in us_selectors.items():
            if name == "GLOBAL":
                continue
            return name, candidates

        if "GLOBAL" in us_selectors:
            return "GLOBAL", us_selectors["GLOBAL"]

        return None, []

    def _find_first_manual_selector(
        self, proxies: Dict[str, dict]
    ) -> Optional[Tuple[str, List[str]]]:
        """Return the first hand-picked Selector group with US nodes."""
        for name, proxy in proxies.items():
            if name == "GLOBAL" or not proxy.get("all"):
                continue
            if str(proxy.get("type", "")).lower() != "selector":
                continue
            candidates = proxy["all"]
            if any(self._is_us_node(node) for node in candidates):
                return name, candidates
        return None

    def _test_delay(self, node_name: str) -> Optional[int]:
        path = f"/proxies/{quote(node_name, safe='')}/delay"
        try:
            response = self._request(
                "GET",
                path,
                params={"timeout": self.timeout_ms, "url": self.test_url},
            )
            response.raise_for_status()
            delay = int(response.json().get("delay", 0))
        except Exception as exc:
            logger.debug("Clash delay test failed for {}: {}", node_name, exc)
            return None

        if delay <= 0:
            return None
        return delay

    def _switch_selector(self, selector: str, node_name: str):
        response = self._request(
            "PUT",
            f"/proxies/{quote(selector, safe='')}",
            json={"name": node_name},
        )
        response.raise_for_status()

    def get_traffic_speed(self, timeout: float = 1.5) -> Optional[ClashTraffic]:
        """Return current Clash upload/download speed."""
        if not self.enabled:
            return None

        response = None
        try:
            response = self._request("GET", "/traffic", timeout=timeout, stream=True)
            response.raise_for_status()
            if hasattr(response, "iter_lines"):
                payload = None
                for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if not line:
                        continue
                    payload = json.loads(line)
                    break
                if payload is None:
                    return None
            else:
                payload = response.json()
            return ClashTraffic(
                up=max(int(payload.get("up", 0)), 0),
                down=max(int(payload.get("down", 0)), 0),
            )
        except Exception as exc:
            logger.debug("Clash traffic query failed: {}", exc)
            return None
        finally:
            if response is not None and hasattr(response, "close"):
                response.close()

    def switch_to_fast_us_node(self) -> Optional[ClashSwitchResult]:
        """Switch selector to the lowest-latency US node that does not timeout."""
        if not self.enabled:
            return None

        self._ensure_rule_mode()
        proxies = self._get_proxies()
        selector, candidates = self._find_selector(proxies)
        if not selector:
            logger.warning("No Clash proxy selector with US nodes was found")
            return None

        results = []
        for node in candidates:
            if not self._is_us_node(node):
                continue
            delay = self._test_delay(node)
            if delay is not None:
                results.append((delay, node))

        if not results:
            logger.warning("No available US Clash node passed delay testing")
            return None

        delay, node = min(results, key=lambda item: item[0])
        self._switch_selector(selector, node)
        return ClashSwitchResult(selector=selector, node=node, delay=delay)
