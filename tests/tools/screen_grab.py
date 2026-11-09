"""Fast capture of one screen rectangle with GDI (BitBlt + GetDIBits), for the demo recording.

PIL's ImageGrab took 68 ms per 1600x900 grab here, so a take had ~4 real frames per second (2026-11-09).
"""

import ctypes
import ctypes.wintypes as wt

import numpy as np

_SRCCOPY, _CAPTUREBLT, _DIB_RGB_COLORS = 0x00CC0020, 0x40000000, 0
# Own instances: setting argtypes on ctypes.windll's shared ones would change them for the app's GDI code,
# which runs in the same process while recording.
_user32, _gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
_user32.GetDC.restype = wt.HDC
_user32.GetDC.argtypes = [wt.HWND]
_user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
_gdi32.CreateCompatibleDC.restype = wt.HDC
_gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
_gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
_gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wt.HDC]
_gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
_gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC,
                          ctypes.c_int, ctypes.c_int, wt.DWORD]
_gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class Grabber:
    """grab() → RGB uint8 array (h, w, 3) of the rectangle, reusing the same GDI objects."""

    def __init__(self, x: int, y: int, w: int, h: int):
        self.x, self.y, self.w, self.h = x, y, w, h
        self._screen = _user32.GetDC(0)
        self._dc = _gdi32.CreateCompatibleDC(self._screen)
        self._bmp = _gdi32.CreateCompatibleBitmap(self._screen, w, h)
        _gdi32.SelectObject(self._dc, self._bmp)
        self._info = _BITMAPINFOHEADER(biSize=ctypes.sizeof(_BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                                       biPlanes=1, biBitCount=32, biCompression=0)
        self._buf = np.empty((h, w, 4), dtype=np.uint8)

    def grab(self) -> np.ndarray:
        _gdi32.BitBlt(self._dc, 0, 0, self.w, self.h, self._screen, self.x, self.y, _SRCCOPY | _CAPTUREBLT)
        _gdi32.GetDIBits(self._dc, self._bmp, 0, self.h, self._buf.ctypes.data, ctypes.byref(self._info),
                         _DIB_RGB_COLORS)
        return self._buf[:, :, 2::-1].copy()            # BGRA → RGB

    def close(self) -> None:
        _gdi32.DeleteObject(self._bmp)
        _gdi32.DeleteDC(self._dc)
        _user32.ReleaseDC(0, self._screen)
