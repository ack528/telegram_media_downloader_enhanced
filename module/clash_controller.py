"""Clash external controller helpers."""

import json
from dataclasses import dataclass
from typing import Dict, Optional

import requests
from loguru import logger


@dataclass
class ClashTraffic:
    """Current Clash traffic speed in bytes per second."""

    up: int
    down: int


class ClashController:
    """Small wrapper for read-only Clash external controller APIs."""

    def __init__(self, config: dict):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.base_url = self._normalize_base_url(
            self.config.get("controller", "http://127.0.0.1:9097")
        )
        self.secret = str(self.config.get("secret", "999"))

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
        timeout = kwargs.pop("timeout", 5)
        return requests.request(
            method,
            url,
            headers=self.headers,
            timeout=timeout,
            **kwargs,
        )

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
