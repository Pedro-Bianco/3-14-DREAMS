"""Open app windows: list, find by name, bring to front, minimize, maximize, close.

Closing sends WM_CLOSE (the same as the window's X), so the app can still ask to save; a process
is never killed.
"""

import ctypes
import ctypes.wintypes as wt
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x80
_SW_MAXIMIZE, _SW_MINIMIZE, _SW_RESTORE = 3, 6, 9
_WM_CLOSE, _WM_COMMAND = 0x0010, 0x0111
_MIN_ALL = 419                       # taskbar command behind "minimize all windows"
_VK_MENU, _KEYEVENTF_KEYUP = 0x12, 0x2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Executable → name people say. Anything else shows its executable name, capitalized.
FRIENDLY = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "code": "VS Code",
    "notepad": "Bloco de Notas", "explorer": "Explorador de Arquivos", "winword": "Word",
    "excel": "Excel", "powerpnt": "PowerPoint", "outlook": "Outlook", "spotify": "Spotify",
    "discord": "Discord", "whatsapp": "WhatsApp", "steam": "Steam", "vlc": "VLC",
    "calculatorapp": "Calculadora", "mspaint": "Paint", "windowsterminal": "Terminal",
    "cmd": "Prompt de Comando", "powershell": "PowerShell", "taskmgr": "Gerenciador de Tarefas",
    "obs64": "OBS Studio", "whatsapp.root": "WhatsApp", "systemsettings": "Configurações",
}
# Shell pieces that show up as visible windows but are not apps people open.
_SHELL = {"textinputhost", "shellexperiencehost", "searchhost", "startmenuexperiencehost", "lockapp",
          "searchapp", "widgets"}
# Store apps all run inside this host: their real name is the window title.
_STORE_HOST = "applicationframehost"


@dataclass
class Window:
    hwnd: int
    title: str
    exe: str          # executable name without .exe, lowercase

    @property
    def name(self) -> str:
        if self.exe == _STORE_HOST:
            return self.title
        return FRIENDLY.get(self.exe, self.exe.capitalize())


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def match(windows: list[Window], query: str) -> list[Window]:
    """Windows whose friendly name, executable or title contain what was said (no accents/case).
    A name match wins over a title match: "chrome" must not pick a tab titled "Chrome tips"."""
    q = _plain(query).strip()
    if not q:
        return []
    by_name = [w for w in windows if q in _plain(w.name) or q in w.exe]
    return by_name or [w for w in windows if q in _plain(w.title)]


def _exe_of(hwnd: int) -> tuple[int, str]:
    pid = wt.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return pid.value, ""
    try:
        size = wt.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return pid.value, Path(buffer.value).stem.lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def list_windows() -> list[Window]:
    """Visible top-level app windows, top of the stack first; not tool windows, owned popups
    or PI dreams itself."""
    user32 = ctypes.windll.user32
    own_pid, found = os.getpid(), []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, _GW_OWNER)
                and not user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                pid, exe = _exe_of(hwnd)
                if pid != own_pid and exe and exe not in _SHELL:
                    title = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, title, length + 1)
                    found.append(Window(hwnd, title.value, exe))
        return True

    user32.EnumWindows(each, 0)
    return found


def bring_to_front(w: Window) -> None:
    user32 = ctypes.windll.user32
    if user32.IsIconic(w.hwnd):
        user32.ShowWindow(w.hwnd, _SW_RESTORE)
    # Windows refuses focus changes from a background process; a synthetic Alt tap is the
    # documented way to be allowed to call SetForegroundWindow.
    user32.keybd_event(_VK_MENU, 0, 0, 0)
    user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(w.hwnd)


def minimize(w: Window) -> None:
    ctypes.windll.user32.ShowWindow(w.hwnd, _SW_MINIMIZE)


def maximize(w: Window) -> None:
    ctypes.windll.user32.ShowWindow(w.hwnd, _SW_MAXIMIZE)


def minimize_all() -> None:
    user32 = ctypes.windll.user32
    user32.PostMessageW(user32.FindWindowW("Shell_TrayWnd", None), _WM_COMMAND, _MIN_ALL, 0)


def close(w: Window) -> None:
    ctypes.windll.user32.PostMessageW(w.hwnd, _WM_CLOSE, 0, 0)
