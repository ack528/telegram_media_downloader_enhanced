"""Util module to handle logs."""
import ctypes
import logging
import os


class LogFilter(logging.Filter):
    """
    Custom Log Filter.

    Ignore logs from specific functions.
    """

    # pylint: disable = W0221
    def filter(self, record):
        if (
            "This property is deprecated. Please use reply_parameters instead"
            in record.getMessage()
        ):
            return False
        if record.funcName in ("invoke"):
            return False
        return True


def disable_quick_edit_mode():
    """Disable Windows console QuickEdit mode to avoid accidental pauses."""
    if os.name != "nt":
        return

    kernel32 = ctypes.windll.kernel32
    stdin_handle = kernel32.GetStdHandle(-10)
    if stdin_handle in (0, -1):
        return

    mode = ctypes.c_uint()
    if not kernel32.GetConsoleMode(stdin_handle, ctypes.byref(mode)):
        return

    enable_extended_flags = 0x0080
    enable_quick_edit_mode = 0x0040
    new_mode = (mode.value | enable_extended_flags) & ~enable_quick_edit_mode
    kernel32.SetConsoleMode(stdin_handle, new_mode)
