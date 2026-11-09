"""One instance per user.

Two open copies listened to the same microphone and doubled the LLM queue (measured
2026-10-16). The second instance wakes the first one (it may be asleep in the tray) and exits.
"""

import ctypes
import logging

log = logging.getLogger(__name__)

_MUTEX_NAME = "Local\\PIDreams"
_ERROR_ALREADY_EXISTS = 183          # ERROR_ALREADY_EXISTS
_SW_RESTORE = 9

_mutex = None                   # keeps the handle alive while the app runs


def acquire(window_title: str) -> bool:
    """True if this is the only instance; False if another one is already open."""
    global _mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if ctypes.get_last_error() != _ERROR_ALREADY_EXISTS:
        return True

    from pidreams.ui.tray import wake_running_copy

    if wake_running_copy():
        log.info("PI dreams is already open; asked it to wake")
        return False
    user32 = ctypes.windll.user32                 # an older copy without the tray icon
    window = user32.FindWindowW(None, window_title)
    if window:
        user32.ShowWindow(window, _SW_RESTORE)
        user32.SetForegroundWindow(window)
    log.info("PI dreams is already open; brought the existing window to the front")
    return False
