"""Network watchdog state shared by download tasks."""

_network_epoch = 0


def get_network_epoch() -> int:
    """Return current network route generation."""
    return _network_epoch


def bump_network_epoch() -> int:
    """Notify active downloads that network route changed."""
    global _network_epoch
    _network_epoch += 1
    return _network_epoch
