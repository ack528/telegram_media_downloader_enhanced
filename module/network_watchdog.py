"""Network watchdog state shared by download tasks."""

import threading
import time
from typing import Optional

_network_epoch = 0
_offline_waiters = 0
_offline_lock = threading.Lock()
_last_route_switch: Optional[dict] = None


def get_network_epoch() -> int:
    """Return current network route generation."""
    return _network_epoch


def bump_network_epoch() -> int:
    """Notify active downloads that network route changed."""
    global _network_epoch
    _network_epoch += 1
    return _network_epoch


def network_wait_started():
    """A download started waiting for Telegram connectivity."""
    global _offline_waiters
    with _offline_lock:
        _offline_waiters += 1


def network_wait_finished():
    """A download stopped waiting for Telegram connectivity."""
    global _offline_waiters
    with _offline_lock:
        _offline_waiters = max(_offline_waiters - 1, 0)


def is_waiting_for_network() -> bool:
    """Return whether any download is currently waiting for the network."""
    return _offline_waiters > 0


def record_route_switch(selector: str, node: str, delay: int):
    """Remember the most recent automatic proxy node switch."""
    global _last_route_switch
    _last_route_switch = {
        "time": int(time.time()),
        "selector": selector,
        "node": node,
        "delay": delay,
    }


def get_last_route_switch() -> Optional[dict]:
    """Return the most recent automatic proxy node switch, if any."""
    return _last_route_switch
