"""Is a game running? Then the app closes completely (no chance of waking mid-match, nothing
running next to an anticheat).

Two signals, no hooks: Windows' own "full-screen Direct3D app" state (the one it uses to hold
notifications during games; a full-screen video reports QUNS_BUSY instead and is ignored), and
process names from the user's list for borderless-window games. Listing the processes took
~14 ms for 122 processes (measured 2026-11-08), checked every 3 s.
"""

import ctypes

import psutil

_QUNS_RUNNING_D3D_FULL_SCREEN = 3


def _fullscreen_d3d() -> bool:
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return state.value == _QUNS_RUNNING_D3D_FULL_SCREEN


def game_running(games: list[str]) -> str | None:
    """What gave the game away (for the log), or None."""
    if _fullscreen_d3d():
        return "full-screen game"
    wanted = {name.strip().lower() for name in games if name.strip()}
    if not wanted:
        return None
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in wanted:
            return name
    return None
