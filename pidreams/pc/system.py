"""Screen brightness, lock, and scheduled shutdown/restart — Windows' own mechanisms, no
administrator rights.

Brightness: laptop panels answer WMI; external monitors answer DDC/CI (dxva2). Measured on
2026-11-01 with two external monitors: ~66 ms to read, ~60 ms to write each.
"""

import ctypes
import ctypes.wintypes as wt
import subprocess

_NO_WINDOW = 0x08000000                     # CREATE_NO_WINDOW: no console flashing
_NOTHING_SCHEDULED = 1116                   # shutdown /a when there is nothing to cancel


class _PhysicalMonitor(ctypes.Structure):
    _fields_ = [("handle", wt.HANDLE), ("description", wt.WCHAR * 128)]


def _ddc_monitors() -> list[tuple[ctypes.Array, int]]:
    """(array of physical monitors, count) per display; the caller destroys them."""
    user32, dxva2, result = ctypes.windll.user32, ctypes.WinDLL("dxva2"), []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    def each(hmon, _hdc, _rect, _):
        count = wt.DWORD()
        if dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)) and count.value:
            monitors = (_PhysicalMonitor * count.value)()
            if dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count, monitors):
                result.append((monitors, count.value))
        return True

    user32.EnumDisplayMonitors(None, None, each, 0)
    return result


_LAPTOP_PANEL: list[bool | None] = [None]     # asked once: the WMI query costs ~0.6 s


def _has_laptop_panel() -> bool:
    if _LAPTOP_PANEL[0] is None:
        count = _powershell("(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness "
                            "-ErrorAction SilentlyContinue | Measure-Object).Count")
        _LAPTOP_PANEL[0] = count.isdigit() and int(count) > 0
    return _LAPTOP_PANEL[0]


def _powershell(command: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True,
                          text=True, timeout=10, creationflags=_NO_WINDOW).stdout.strip()


def get_brightness() -> int | None:
    """Brightness of the first screen that answers, or None when none accepts software control."""
    if _has_laptop_panel():
        laptop = _powershell("(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness "
                             "| Select-Object -First 1).CurrentBrightness")
        if laptop.isdigit():
            return int(laptop)
    dxva2 = ctypes.WinDLL("dxva2")
    value = None
    for monitors, count in _ddc_monitors():
        for m in monitors:
            low, current, high = wt.DWORD(), wt.DWORD(), wt.DWORD()
            if value is None and dxva2.GetMonitorBrightness(m.handle, ctypes.byref(low), ctypes.byref(current),
                                                            ctypes.byref(high)) and high.value:
                value = round(100 * (current.value - low.value) / (high.value - low.value))
        dxva2.DestroyPhysicalMonitors(count, monitors)
    return value


def set_brightness(percent: int) -> int:
    """Applies to every screen that accepts it; returns how many did."""
    done = 0
    laptop = "" if not _has_laptop_panel() else _powershell("$m = Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods "
                         "-ErrorAction SilentlyContinue; if ($m) { $m | Invoke-CimMethod -MethodName "
                         f"WmiSetBrightness -Arguments @{{Timeout=0; Brightness={percent}}} | Out-Null; "
                         "@($m).Count } else { 0 }")
    done += int(laptop) if laptop.isdigit() else 0
    dxva2 = ctypes.WinDLL("dxva2")
    for monitors, count in _ddc_monitors():
        for m in monitors:
            low, current, high = wt.DWORD(), wt.DWORD(), wt.DWORD()
            if dxva2.GetMonitorBrightness(m.handle, ctypes.byref(low), ctypes.byref(current), ctypes.byref(high)):
                target = low.value + round((high.value - low.value) * percent / 100)
                done += bool(dxva2.SetMonitorBrightness(m.handle, target))
        dxva2.DestroyPhysicalMonitors(count, monitors)
    return done


def lock() -> None:
    ctypes.windll.user32.LockWorkStation()


def shutdown_command(mode: str, seconds: int) -> list[str]:
    """mode "desligar" or "reiniciar". Pure: unit tests check the exact command."""
    flag = {"desligar": "/s", "reiniciar": "/r"}[mode]
    return ["shutdown", flag, "/t", str(seconds), "/c", f"Pedido ao PI dreams ({mode})."]


def schedule(mode: str, seconds: int) -> None:
    subprocess.run(shutdown_command(mode, seconds), check=True, timeout=10, creationflags=_NO_WINDOW)


def cancel_shutdown() -> bool:
    """True if a scheduled shutdown/restart was cancelled; False if there was none."""
    code = subprocess.run(["shutdown", "/a"], timeout=10, creationflags=_NO_WINDOW).returncode
    if code not in (0, _NOTHING_SCHEDULED):
        raise RuntimeError(f"shutdown /a returned {code}")
    return code == 0

