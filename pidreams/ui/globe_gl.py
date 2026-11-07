"""The globe's frames drawn by the graphics card (OpenGL through WGL, on any Windows GPU).

The globe still decides every point, colour and mark on the CPU (ui/globe.py); this only replaces the
brush: instead of writing pixels into a numpy image and copying it to the window, the points are sent
to the GPU at once and the sphere's shading is a small shader. Measured at 2330x926 with 214 000
points (2026-11-07): ~2 ms a frame against ~10 ms with GDI, so 120 frames/s and more. When OpenGL
cannot start (a remote session, an old driver) the globe keeps drawing with GDI.
"""

import ctypes
from ctypes import wintypes as W

import numpy as np

_user32, _gdi32, _opengl32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.opengl32


class _PixelFormat(ctypes.Structure):
    _fields_ = [(name, kind) for name, kind in (
        ("nSize", W.WORD), ("nVersion", W.WORD), ("dwFlags", W.DWORD), ("iPixelType", ctypes.c_ubyte),
        ("cColorBits", ctypes.c_ubyte), ("cRedBits", ctypes.c_ubyte), ("cRedShift", ctypes.c_ubyte),
        ("cGreenBits", ctypes.c_ubyte), ("cGreenShift", ctypes.c_ubyte), ("cBlueBits", ctypes.c_ubyte),
        ("cBlueShift", ctypes.c_ubyte), ("cAlphaBits", ctypes.c_ubyte), ("cAlphaShift", ctypes.c_ubyte),
        ("cAccumBits", ctypes.c_ubyte), ("cAccumRedBits", ctypes.c_ubyte), ("cAccumGreenBits", ctypes.c_ubyte),
        ("cAccumBlueBits", ctypes.c_ubyte), ("cAccumAlphaBits", ctypes.c_ubyte), ("cDepthBits", ctypes.c_ubyte),
        ("cStencilBits", ctypes.c_ubyte), ("cAuxBuffers", ctypes.c_ubyte), ("iLayerType", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte), ("dwLayerMask", W.DWORD), ("dwVisibleMask", W.DWORD),
        ("dwDamageMask", W.DWORD))]


_user32.GetDC.restype, _user32.GetDC.argtypes = W.HDC, [W.HWND]
_user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
_gdi32.ChoosePixelFormat.argtypes = [W.HDC, ctypes.POINTER(_PixelFormat)]
_gdi32.SetPixelFormat.argtypes = [W.HDC, ctypes.c_int, ctypes.POINTER(_PixelFormat)]
_gdi32.SwapBuffers.argtypes = [W.HDC]
_opengl32.wglCreateContext.restype, _opengl32.wglCreateContext.argtypes = W.HANDLE, [W.HDC]
_opengl32.wglMakeCurrent.argtypes = [W.HDC, W.HANDLE]
_opengl32.wglDeleteContext.argtypes = [W.HANDLE]
_opengl32.wglGetProcAddress.restype, _opengl32.wglGetProcAddress.argtypes = ctypes.c_void_p, [ctypes.c_char_p]

_BG_VS = """#version 330 compatibility
layout(location = 0) in vec2 corner;
out vec2 pix;
uniform vec2 size;
void main() { pix = vec2((corner.x * 0.5 + 0.5) * size.x, (0.5 - corner.y * 0.5) * size.y); gl_Position = vec4(corner, 0, 1); }"""
# The same shading as GlobeView._shading_lut: the sphere lit from the front and a glow at its edge.
_BG_FS = """#version 330 compatibility
in vec2 pix;
out vec4 color;
uniform vec2 center; uniform float radius; uniform vec3 bg, sphere, land;
void main() {
    float d = distance(pix, center) / max(radius, 1.0);
    vec3 c = d < 1.0 ? sphere * (0.55 + 0.45 * sqrt(1.0 - d * d)) + bg * 0.2 : bg;
    float glow = clamp(1.0 - abs(d - 1.0) * 14.0, 0.0, 1.0) * 0.55
               + clamp(1.0 - (d - 1.0) * 3.0, 0.0, 1.0) * float(d > 1.0) * 0.12;
    color = vec4(min((c + glow * land * 0.45) / 255.0, 1.0), 1.0);
}"""
# Points, lines and the circles' segments: window pixels and colour 0..255 already scaled by strength.
_PT_VS = """#version 330 compatibility
layout(location = 0) in vec2 pos;
layout(location = 1) in vec3 rgb;
uniform vec2 size; uniform float point_size;
out vec3 col;
void main() {
    gl_Position = vec4(pos.x / size.x * 2.0 - 1.0, 1.0 - pos.y / size.y * 2.0, 0, 1);
    gl_PointSize = point_size;
    col = rgb / 255.0;
}"""
# halo = 1: a 3-pixel point, the centre at full colour and its four neighbours at 35%, as GlobeView._plot.
_PT_FS = """#version 330 compatibility
in vec3 col;
out vec4 color;
uniform int halo;
void main() {
    float k = 1.0;
    if (halo == 1) {
        vec2 q = abs(gl_PointCoord - 0.5) * 3.0;
        k = (q.x < 0.5 && q.y < 0.5) ? 1.0 : ((q.x < 0.5 || q.y < 0.5) ? 0.35 : 0.0);
        if (k == 0.0) discard;
    }
    color = vec4(col * k, 1.0);
}"""
_TX_VS = """#version 330 compatibility
layout(location = 0) in vec2 pos;
layout(location = 1) in vec2 uv;
uniform vec2 size;
out vec2 tc;
void main() { gl_Position = vec4(pos.x / size.x * 2.0 - 1.0, 1.0 - pos.y / size.y * 2.0, 0, 1); tc = uv; }"""
_TX_FS = """#version 330 compatibility
in vec2 tc;
out vec4 color;
uniform sampler2D tex;
void main() { color = texture(tex, tc); }"""


class GLUnavailable(RuntimeError):
    pass


def _rgb(hex_color: str) -> tuple[float, float, float]:
    return tuple(float(int(hex_color[i:i + 2], 16)) for i in (1, 3, 5))


class GlobePainter:
    """One OpenGL context on one native window. The globe calls begin(), points()/ellipse()/
    polyline()/text() as it decides the frame, then present()."""

    def __init__(self, hwnd: int, bg: str, sphere: str, land: str):
        try:
            from OpenGL import GL
            from OpenGL.GL import shaders
        except Exception as e:                       # noqa: BLE001 — no PyOpenGL: the GDI path draws
            raise GLUnavailable(f"PyOpenGL: {e}") from e
        self.GL, self.hwnd = GL, hwnd
        self._hdc = _user32.GetDC(hwnd)
        fmt = _PixelFormat(ctypes.sizeof(_PixelFormat), 1, 0x4 | 0x20 | 0x1, 0, 32)   # window | OpenGL | double
        index = _gdi32.ChoosePixelFormat(self._hdc, ctypes.byref(fmt))
        if not index or not _gdi32.SetPixelFormat(self._hdc, index, ctypes.byref(fmt)):
            raise GLUnavailable("no OpenGL pixel format for this window")
        self._ctx = _opengl32.wglCreateContext(self._hdc)
        if not self._ctx or not _opengl32.wglMakeCurrent(self._hdc, self._ctx):
            raise GLUnavailable("could not create an OpenGL context")
        try:
            swap = _opengl32.wglGetProcAddress(b"wglSwapIntervalEXT")
            if swap:
                ctypes.WINFUNCTYPE(W.BOOL, ctypes.c_int)(swap)(0)   # no waiting for the screen: the globe paces itself
            compile_ = lambda vs, fs: shaders.compileProgram(shaders.compileShader(vs, GL.GL_VERTEX_SHADER),
                                                              shaders.compileShader(fs, GL.GL_FRAGMENT_SHADER))
            self._bg_prog, self._pt_prog, self._tx_prog = (compile_(_BG_VS, _BG_FS), compile_(_PT_VS, _PT_FS),
                                                           compile_(_TX_VS, _TX_FS))
        except Exception as e:                       # noqa: BLE001 — OpenGL older than 3.3, a broken driver
            self.release()
            raise GLUnavailable(f"OpenGL: {e}") from e
        self.renderer = GL.glGetString(GL.GL_RENDERER).decode(errors="replace")
        self._colors = {"bg": _rgb(bg), "sphere": _rgb(sphere), "land": _rgb(land)}
        self._quad = self._buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32), (2,))
        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        self._textures: dict[tuple, tuple[int, int, int]] = {}
        GL.glEnable(GL.GL_PROGRAM_POINT_SIZE)
        GL.glEnable(0x8861)                          # GL_POINT_SPRITE: gl_PointCoord in the compatibility profile

    def _buffer(self, data: np.ndarray, sizes: tuple[int, ...]):
        GL = self.GL
        vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(vao)
        vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_STATIC_DRAW)
        stride, offset = 4 * sum(sizes), 0
        for loc, n in enumerate(sizes):
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, n, GL.GL_FLOAT, False, stride, ctypes.c_void_p(offset))
            offset += 4 * n
        return vao, vbo

    # ── one frame ──

    def begin(self, w: int, h: int, radius: float, cx: float, cy: float) -> None:
        self._frame = (w, h, radius, cx, cy)
        self._halo: list[np.ndarray] = []            # (n, 5) x, y, r, g, b
        self._plain: list[np.ndarray] = []
        self._lines: list[tuple[np.ndarray, float]] = []   # (segments as (n, 5), width)
        self._labels: list[tuple[float, float, str, str, int]] = []

    def points(self, x: np.ndarray, y: np.ndarray, rgb: np.ndarray, glow: bool) -> None:
        """x, y: whole window pixels; rgb: (n, 3) 0..255 with the strength already applied."""
        block = np.empty((len(x), 5), np.float32)
        block[:, 0], block[:, 1], block[:, 2:] = x + 0.5, y + 0.5, rgb
        (self._halo if glow else self._plain).append(block)

    def ellipse(self, x: float, y: float, r: float, color: str, width: int = 1) -> None:
        a = np.linspace(0, 2 * np.pi, 49, dtype=np.float32)
        px, py = x + r * np.cos(a), y + r * np.sin(a)
        self._segments(np.column_stack([px, py]), color, width)

    def polyline(self, points: np.ndarray, color: str, dashed: bool = False) -> None:
        points = np.asarray(points, np.float32)
        if len(points) < 2:
            return
        if not dashed:
            self._segments(points, color, 1)
            return
        # 4 pixels on, 3 off, along the line (as the GDI dashed pen)
        steps = np.hypot(*np.diff(points, axis=0).T)
        dist = np.concatenate([[0], np.cumsum(steps)])
        marks = np.arange(0, dist[-1], 7.0)
        for start in marks:
            ends = np.array([start, min(start + 4.0, dist[-1])])
            xs, ys = np.interp(ends, dist, points[:, 0]), np.interp(ends, dist, points[:, 1])
            self._segments(np.column_stack([xs, ys]), color, 1)

    def _segments(self, path: np.ndarray, color: str, width: int) -> None:
        seg = np.empty((2 * (len(path) - 1), 5), np.float32)
        seg[0::2, :2], seg[1::2, :2] = path[:-1], path[1:]
        seg[:, 2:] = _rgb(color)
        self._lines.append((seg, float(width)))

    def text(self, x: float, y: float, text: str, color: str, size_px: int) -> None:
        self._labels.append((x, y, text, color, size_px))

    def present(self) -> None:
        GL = self.GL
        w, h, radius, cx, cy = self._frame
        _opengl32.wglMakeCurrent(self._hdc, self._ctx)
        GL.glViewport(0, 0, w, h)
        GL.glDisable(GL.GL_BLEND)
        GL.glUseProgram(self._bg_prog)
        GL.glUniform2f(GL.glGetUniformLocation(self._bg_prog, "size"), w, h)
        GL.glUniform2f(GL.glGetUniformLocation(self._bg_prog, "center"), cx, cy)
        GL.glUniform1f(GL.glGetUniformLocation(self._bg_prog, "radius"), radius)
        for name, value in self._colors.items():
            GL.glUniform3f(GL.glGetUniformLocation(self._bg_prog, name), *value)
        GL.glBindVertexArray(self._quad[0])
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        # Brighter wins where points overlap, as np.maximum did.
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendEquation(GL.GL_MAX)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
        GL.glUseProgram(self._pt_prog)
        GL.glUniform2f(GL.glGetUniformLocation(self._pt_prog, "size"), w, h)
        for blocks, size, halo in ((self._halo, 3.0, 1), (self._plain, 1.0, 0)):
            if blocks:
                self._draw(np.concatenate(blocks), GL.GL_POINTS, size, halo)
        for seg, width in self._lines:
            GL.glLineWidth(width)
            self._draw(seg, GL.GL_LINES, 1.0, 0)
        if self._labels:
            self._draw_labels(w, h)
        _gdi32.SwapBuffers(self._hdc)

    def _draw(self, data: np.ndarray, mode: int, point_size: float, halo: int) -> None:
        GL = self.GL
        GL.glUniform1f(GL.glGetUniformLocation(self._pt_prog, "point_size"), point_size)
        GL.glUniform1i(GL.glGetUniformLocation(self._pt_prog, "halo"), halo)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.nbytes, data, GL.GL_STREAM_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 20, ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, False, 20, ctypes.c_void_p(8))
        GL.glDrawArrays(mode, 0, len(data))

    def _texture(self, text: str, color: str, size_px: int) -> tuple[int, int, int]:
        key = (text, color, size_px)
        if key not in self._textures:
            from PIL import Image, ImageDraw, ImageFont
            try:
                font = ImageFont.truetype("segoeui.ttf", size_px)
            except OSError:
                font = ImageFont.load_default()
            left, top, right, bottom = font.getbbox(text)
            image = Image.new("RGBA", (right - left + 2, bottom - top + 2), (0, 0, 0, 0))
            ImageDraw.Draw(image).text((1 - left, 1 - top), text, font=font, fill=color)
            GL = self.GL
            tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, image.width, image.height, 0, GL.GL_RGBA,
                            GL.GL_UNSIGNED_BYTE, image.tobytes())
            self._textures[key] = (tex, image.width, image.height)
        return self._textures[key]

    def _draw_labels(self, w: int, h: int) -> None:
        GL = self.GL
        GL.glBlendEquation(GL.GL_FUNC_ADD)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glUseProgram(self._tx_prog)
        GL.glUniform2f(GL.glGetUniformLocation(self._tx_prog, "size"), w, h)
        GL.glUniform1i(GL.glGetUniformLocation(self._tx_prog, "tex"), 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        for x, y, text, color, size_px in self._labels:
            tex, tw, th = self._texture(text, color, size_px)
            x0, y0 = round(x), round(y - th / 2)
            quad = np.array([[x0, y0, 0, 0], [x0 + tw, y0, 1, 0], [x0, y0 + th, 0, 1], [x0 + tw, y0 + th, 1, 1]], np.float32)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glBindVertexArray(self._vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STREAM_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 16, ctypes.c_void_p(0))
            GL.glEnableVertexAttribArray(1)
            GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, False, 16, ctypes.c_void_p(8))
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

    def release(self) -> None:
        if getattr(self, "_ctx", None):
            _opengl32.wglMakeCurrent(None, None)
            _opengl32.wglDeleteContext(self._ctx)
            self._ctx = None
        if getattr(self, "_hdc", None):
            _user32.ReleaseDC(self.hwnd, self._hdc)
            self._hdc = None
