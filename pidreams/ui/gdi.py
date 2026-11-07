"""Drawing straight into a native window with the Windows GDI, double-buffered.

Tk took ~23 ms to show one 2330x926 image (PhotoImage.paste + redraw); copying the same pixels with
GDI takes ~3.5 ms (measured 2026-11-07). The globe draws each frame into a memory bitmap whose
pixels are a numpy array, adds the few marks on top with GDI pens and fonts, and copies it to the
window at once, so nothing flickers.
"""

import ctypes
from ctypes import wintypes as W

import numpy as np

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_gdi32.CreateDIBSection.restype = W.HBITMAP
_gdi32.CreateCompatibleDC.restype = W.HDC
_gdi32.SelectObject.restype = W.HGDIOBJ
_gdi32.CreatePen.restype = W.HPEN
_gdi32.CreateFontW.restype = W.HFONT
_gdi32.GetStockObject.restype = W.HGDIOBJ
_user32.GetDC.restype = W.HDC
for _f, _args in ((_gdi32.CreateDIBSection, [W.HDC, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p), W.HANDLE, W.DWORD]),
                  (_gdi32.SelectObject, [W.HDC, W.HGDIOBJ]), (_gdi32.DeleteObject, [W.HGDIOBJ]),
                  (_gdi32.DeleteDC, [W.HDC]), (_gdi32.CreateCompatibleDC, [W.HDC]),
                  (_gdi32.BitBlt, [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HDC,
                                   ctypes.c_int, ctypes.c_int, W.DWORD]),
                  (_gdi32.StretchBlt, [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HDC,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.DWORD]),
                  (_gdi32.SetStretchBltMode, [W.HDC, ctypes.c_int]),
                  (_gdi32.Ellipse, [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                  (_gdi32.Polyline, [W.HDC, ctypes.c_void_p, ctypes.c_int]),
                  (_gdi32.TextOutW, [W.HDC, ctypes.c_int, ctypes.c_int, W.LPCWSTR, ctypes.c_int]),
                  (_gdi32.CreatePen, [ctypes.c_int, ctypes.c_int, W.COLORREF]),
                  (_gdi32.SetTextColor, [W.HDC, W.COLORREF]), (_gdi32.SetBkMode, [W.HDC, ctypes.c_int]),
                  (_user32.GetDC, [W.HWND]), (_user32.ReleaseDC, [W.HWND, W.HDC])):
    _f.argtypes = _args

_SRCCOPY, _NULL_BRUSH, _TRANSPARENT, _PS_SOLID, _PS_DASH, _COLORONCOLOR = 0x00CC0020, 5, 1, 0, 1, 3


def fine_timer(on: bool) -> None:
    """1 ms timer resolution while something animates. Windows' default 15.6 ms steps turned Tk's
    after(16) into 31 ms now and then: a visible hitch at 60 frames/s (app log, 2026-11-07)."""
    winmm = ctypes.windll.winmm
    (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


def _colorref(hex_color: str) -> int:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return r | g << 8 | b << 16


class Surface:
    """A memory bitmap the size of the window: fill pixels (RGB numpy), add marks, then present()."""

    def __init__(self):
        self._dc = None
        self._bitmap = None
        self._old = None
        self.size = (0, 0)
        self.pixels: np.ndarray | None = None          # (h, w, 4) uint8, BGRX
        self._pens: dict[tuple[str, int, bool], int] = {}
        self._fonts: dict[int, int] = {}

    def resize(self, w: int, h: int) -> bool:
        """True when the bitmap was (re)made, all black: the caller paints it again."""
        if (w, h) == self.size:
            return False
        self.release()
        header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down
        bits = ctypes.c_void_p()
        self._dc = _gdi32.CreateCompatibleDC(None)
        self._bitmap = _gdi32.CreateDIBSection(self._dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        self._old = _gdi32.SelectObject(self._dc, self._bitmap)
        buffer = (ctypes.c_uint8 * (w * h * 4)).from_address(bits.value)
        self.pixels = np.frombuffer(buffer, np.uint8).reshape(h, w, 4)
        self.size = (w, h)
        return True

    def put(self, rgb: np.ndarray, x: int = 0, y: int = 0) -> None:
        h, w = rgb.shape[:2]
        region = self.pixels[y:y + h, x:x + w]
        region[..., 0], region[..., 1], region[..., 2] = rgb[..., 2], rgb[..., 1], rgb[..., 0]

    def fill(self, rgb) -> None:
        self.pixels[..., 0], self.pixels[..., 1], self.pixels[..., 2] = rgb[2], rgb[1], rgb[0]

    def _pen(self, color: str, width: int, dashed: bool) -> int:
        key = (color, width, dashed)
        if key not in self._pens:
            self._pens[key] = _gdi32.CreatePen(_PS_DASH if dashed else _PS_SOLID, 1 if dashed else width, _colorref(color))
        return self._pens[key]

    def ellipse(self, x: float, y: float, r: float, color: str, width: int = 1) -> None:
        _gdi32.SelectObject(self._dc, self._pen(color, width, False))
        _gdi32.SelectObject(self._dc, _gdi32.GetStockObject(_NULL_BRUSH))
        _gdi32.Ellipse(self._dc, round(x - r), round(y - r), round(x + r) + 1, round(y + r) + 1)

    def polyline(self, points: np.ndarray, color: str, dashed: bool = False) -> None:
        if len(points) < 2:
            return
        _gdi32.SelectObject(self._dc, self._pen(color, 1, dashed))
        _gdi32.SetBkMode(self._dc, _TRANSPARENT)
        pts = np.ascontiguousarray(np.round(points), dtype=np.int32)
        _gdi32.Polyline(self._dc, pts.ctypes.data_as(ctypes.c_void_p), len(pts))

    def text(self, x: float, y: float, text: str, color: str, size_px: int) -> None:
        if size_px not in self._fonts:
            self._fonts[size_px] = _gdi32.CreateFontW(-size_px, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 4, 0, "Segoe UI")
        _gdi32.SelectObject(self._dc, self._fonts[size_px])
        _gdi32.SetBkMode(self._dc, _TRANSPARENT)
        _gdi32.SetTextColor(self._dc, _colorref(color))
        _gdi32.TextOutW(self._dc, round(x), round(y - size_px / 2 - 1), text, len(text))

    def present(self, hwnd: int, scale: int = 1) -> None:
        """Copies the bitmap to the window at once, stretched scale times (GDI does it almost for free)."""
        w, h = self.size
        dc = _user32.GetDC(hwnd)
        try:
            if scale == 1:
                _gdi32.BitBlt(dc, 0, 0, w, h, self._dc, 0, 0, _SRCCOPY)
            else:
                _gdi32.SetStretchBltMode(dc, _COLORONCOLOR)
                _gdi32.StretchBlt(dc, 0, 0, w * scale, h * scale, self._dc, 0, 0, w, h, _SRCCOPY)
        finally:
            _user32.ReleaseDC(hwnd, dc)

    def release(self) -> None:
        if self._dc:
            _gdi32.SelectObject(self._dc, self._old)
            _gdi32.DeleteObject(self._bitmap)
            _gdi32.DeleteDC(self._dc)
        for handle in [*self._pens.values(), *self._fonts.values()]:
            _gdi32.DeleteObject(handle)
        self._dc = self._bitmap = self._old = self.pixels = None
        self._pens, self._fonts, self.size = {}, {}, (0, 0)
