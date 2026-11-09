"""Start with Windows: one value in the user's Run key, started with --tray (asleep in the tray).

Per user and without administrator rights; visible in Task Manager > Startup apps. The
uninstaller deletes the value (installer/pidreams.iss).
"""

import subprocess
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PI dreams"


def command() -> str:
    """The packaged exe, or this Python running the package (development)."""
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable, "--tray"])
    # pythonw: no console window at login. The Run key starts in no particular folder, so the
    # repository goes on the path explicitly.
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    root = str(Path(__file__).resolve().parents[2])
    bootstrap = f"import sys,runpy;sys.path.insert(0,{root!r});runpy.run_module('pidreams',run_name='__main__')"
    return subprocess.list2cmdline([pythonw, "-c", bootstrap, "--tray"])


def is_enabled(key_path: str = RUN_KEY) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def set_enabled(on: bool, key_path: str = RUN_KEY) -> None:
    """Raises OSError when the registry refuses (shown to the user by the caller)."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if on:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
