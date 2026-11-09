"""Notification-area (tray) icon, with ctypes and no extra dependency.

A message-only window created on the Tk thread receives the icon's clicks: Tk's event loop
dispatches the messages of every window of its thread, so no thread of our own is needed. The
same window answers the "wake" message a second copy of the app sends (core/single_instance).
"""

import ctypes
import ctypes.wintypes as wt
import logging
from pathlib import Path
from typing import Callable

from pidreams.core import paths

log = logging.getLogger(__name__)

WINDOW_CLASS = "PIDreamsTray"
WAKE_MESSAGE = "PIDreams.Wake"

TIPS = {
    "listening": "PI dreams — ouvindo palmas",
    "paused": "PI dreams — escuta de palmas pausada",
    "no_mic": "PI dreams — sem microfone para ouvir palmas",
}

_ICON = Path(__file__).resolve().parents[1] / "assets" / "pidreams.ico"

_WM_APP_TRAY = 0x8001                    # WM_APP + 1
_WM_NULL, _WM_LBUTTONUP, _WM_RBUTTONUP = 0x0000, 0x0202, 0x0205
_HWND_MESSAGE = wt.HWND(-3)
_NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
_NIF_MESSAGE, _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x1, 0x2, 0x4, 0x10
_NIIF_USER, _NIN_BALLOONUSERCLICK = 0x4, 0x0405      # balloon with the app's own icon; click on it
_MF_STRING, _MF_CHECKED, _MF_SEPARATOR = 0x0, 0x8, 0x800
_TPM_RIGHTBUTTON, _TPM_RETURNCMD, _TPM_NONOTIFY = 0x2, 0x100, 0x80
_IMAGE_ICON, _LR_LOADFROMFILE, _LR_DEFAULTSIZE = 1, 0x10, 0x40
_CMD_OPEN, _CMD_CLAPS, _CMD_QUIT = 1, 2, 3

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wt.HICON)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetModuleHandleW.restype = wt.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
_user32.RegisterClassW.argtypes = [ctypes.c_void_p]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
_user32.CreateWindowExW.restype = wt.HWND
_user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
_user32.DefWindowProcW.restype = _LRESULT
_user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.LoadImageW.restype = wt.HANDLE
_user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
_user32.CreatePopupMenu.restype = wt.HMENU
_user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
_user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
_user32.DestroyMenu.argtypes = [wt.HMENU]
_user32.DestroyWindow.argtypes = [wt.HWND]
_user32.SetForegroundWindow.argtypes = [wt.HWND]
_user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.FindWindowW.restype = wt.HWND
_user32.FindWindowExW.restype = wt.HWND
_user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
_user32.RegisterWindowMessageW.restype = wt.UINT
_user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
_shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]


def wake_running_copy() -> bool:
    """From a second copy: asks the resident one to open its window. False if none answers."""
    window = _user32.FindWindowExW(_HWND_MESSAGE, None, WINDOW_CLASS, None)
    if not window:
        return False
    return bool(_user32.PostMessageW(window, _user32.RegisterWindowMessageW(WAKE_MESSAGE), 0, 0))


def _paused_icon() -> Path:
    """The app icon in gray, made once into the user's cache."""
    target = paths.cache_dir("tray") / "pidreams-paused.ico"
    if not target.exists():
        from PIL import Image

        target.parent.mkdir(parents=True, exist_ok=True)
        image = Image.open(_ICON).convert("RGBA")
        gray = image.convert("LA").convert("RGBA")
        gray.putalpha(image.getchannel("A"))
        gray.save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
    return target


class TrayIcon:
    """on_wake: open the window. on_claps(bool): the user turned listening on/off. on_quit: exit."""

    def __init__(self, on_wake: Callable[[], None], on_claps: Callable[[bool], None],
                 on_quit: Callable[[], None]):
        self._on_wake, self._on_claps, self._on_quit = on_wake, on_claps, on_quit
        self._state = "listening"
        self._shown = False
        self._proc = _WNDPROC(self._window_proc)     # kept alive: Windows calls it
        instance = _kernel32.GetModuleHandleW(None)
        window_class = _WNDCLASSW(lpfnWndProc=self._proc, hInstance=instance, lpszClassName=WINDOW_CLASS)
        _user32.RegisterClassW(ctypes.byref(window_class))
        # Set before the window exists: Windows already calls _window_proc while creating it.
        self._wake_message = _user32.RegisterWindowMessageW(WAKE_MESSAGE)
        self._taskbar_created = _user32.RegisterWindowMessageW("TaskbarCreated")   # Explorer restarted
        self._hwnd = _user32.CreateWindowExW(0, WINDOW_CLASS, WINDOW_CLASS, 0, 0, 0, 0, 0,
                                             _HWND_MESSAGE, None, instance, None)
        self._icons = {"listening": self._load(_ICON)}
        try:
            self._icons["paused"] = self._load(_paused_icon())
        except Exception as e:
            log.warning("paused tray icon: %r", e)
            self._icons["paused"] = self._icons["listening"]
        self._icons["no_mic"] = self._icons["paused"]

    @staticmethod
    def _load(path: Path):
        return _user32.LoadImageW(None, str(path), _IMAGE_ICON, 0, 0, _LR_LOADFROMFILE | _LR_DEFAULTSIZE)

    def _data(self) -> _NOTIFYICONDATAW:
        data = _NOTIFYICONDATAW(cbSize=ctypes.sizeof(_NOTIFYICONDATAW), hWnd=self._hwnd, uID=1,
                                uFlags=_NIF_MESSAGE | _NIF_ICON | _NIF_TIP, uCallbackMessage=_WM_APP_TRAY,
                                hIcon=self._icons[self._state])
        data.szTip = TIPS[self._state]
        return data

    def show(self, state: str) -> None:
        """state: listening, paused or no_mic — always visible in the icon and its tip."""
        self._state = state
        data = self._data()
        if self._shown:
            _shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(data))
        else:
            self._shown = bool(_shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data)))
            if not self._shown:
                log.warning("tray icon could not be added")

    def notify(self, title: str, text: str) -> bool:
        """A Windows notification from the icon (Windows 10/11 show it as a toast). Only while
        the icon is shown; False when it could not be shown."""
        if not self._shown:
            return False
        data = self._data()
        data.uFlags |= _NIF_INFO
        data.szInfoTitle, data.szInfo = title[:63], text[:255]
        data.dwInfoFlags = _NIIF_USER
        return bool(_shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(data)))

    def hide(self) -> None:
        if self._shown:
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._data()))
            self._shown = False

    def destroy(self) -> None:
        self.hide()
        if self._hwnd:
            _user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def _menu(self) -> None:
        menu = _user32.CreatePopupMenu()
        _user32.AppendMenuW(menu, _MF_STRING, _CMD_OPEN, "Abrir o PI")
        listening = self._state != "paused"
        _user32.AppendMenuW(menu, _MF_STRING | (_MF_CHECKED if listening else 0), _CMD_CLAPS, "Ouvir palmas")
        _user32.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, _MF_STRING, _CMD_QUIT, "Sair")
        point = wt.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        _user32.SetForegroundWindow(self._hwnd)      # otherwise the menu does not close on click-away
        command = _user32.TrackPopupMenu(menu, _TPM_RIGHTBUTTON | _TPM_RETURNCMD | _TPM_NONOTIFY,
                                         point.x, point.y, 0, self._hwnd, None)
        _user32.PostMessageW(self._hwnd, _WM_NULL, 0, 0)
        _user32.DestroyMenu(menu)
        if command == _CMD_OPEN:
            self._on_wake()
        elif command == _CMD_CLAPS:
            self._on_claps(not listening)
        elif command == _CMD_QUIT:
            self._on_quit()

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == _WM_APP_TRAY:
                if lparam in (_WM_LBUTTONUP, _NIN_BALLOONUSERCLICK):
                    self._on_wake()
                elif lparam == _WM_RBUTTONUP:
                    self._menu()
                return 0
            if message == self._wake_message:
                self._on_wake()
                return 0
            if message == self._taskbar_created and self._shown:
                self._shown = False
                self.show(self._state)
                return 0
        except Exception:
            log.exception("tray icon")
        return _user32.DefWindowProcW(hwnd, message, wparam, lparam)
