"""The monitor's 3D globe: orthographic projection painted with numpy into one opaque image.

Measured with 10 000 points (2026-11-02): one Canvas item per point 218 ms per frame, an RGBA
image 1751 ms, an opaque image 7.4 ms. So land, borders, satellites and radios are pixels of a
single image, and the few marks on top (earthquakes, the ISS, the selection) are drawn on it.
The image goes to the screen with the Windows GDI (ui/gdi.py): Tk took ~23 ms to show a
2330x926 frame, GDI ~3.5 ms. Nothing runs while the view is hidden. No GPU.
"""

import logging
import math
import statistics
import threading
import time
import tkinter as tk

import numpy as np
from pidreams.monitor import planes as planes_mod, world
from pidreams.ui import gdi, globe_gl, theme

log = logging.getLogger(__name__)

# 120 frames/s, kept steady: the next frame is scheduled from when this one STARTED. Scheduling 40 ms
# after each frame ended made the period 40 ms + the frame's own cost, 15-25 frames/s and uneven.
_FPS_MS = 8                           # a frame takes 2-5 ms on the GPU at 2330x926 (2026-11-07)
_SPIN_PER_S = math.radians(2.0)       # slow idle spin
# Opening animation: from close to the surface out to the whole globe, slowing down at the end,
# while the picture fades in.
_INTRO_S = 1.8
_INTRO_ZOOM = 14.0
_LUT_SIZE = 2048                      # background shading by distance from the centre, d = 0..2 radii
# The opening fills the whole PI dreams window (3440x1369 in the app, 2026-11-07): it is drawn at half
# resolution and stretched by GDI, unnoticeable while it moves and 4x less work.
_INTRO_SCALE = 2
_SAT_REFRESH_S = 1.0                  # low orbits move ~0.4 px/s on a 700 px globe; 1 s is plenty


def _rgb(hex_color: str) -> np.ndarray:
    return np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


_BG = _rgb(theme.BG)
_SPHERE = _rgb(theme.GLOBE_SPHERE)
_LAND = _rgb(theme.CYAN)
_BORDER = _rgb(theme.GLOBE_BORDER)
_SAT = {"internet": _rgb(theme.SAT_INTERNET), "navegacao": _rgb(theme.OK), "clima": _rgb(theme.WARN),
        "estacao": _rgb(theme.SAT_STATION), "outros": _rgb(theme.TEXT)}
_RADIO = _rgb(theme.VIOLET)
_PLANE = _rgb(theme.PEACH)
_MAX_ZOOM = 16.0                      # close enough to tell the planes of a 460 km region apart (research R2)
_HEADING_MIN = 10                     # the selected plane's line ahead: where it will be in 10 minutes
# From this zoom the 1:110m outline (a point every ~67 km) falls apart into loose dots; the 1:50m one
# (every ~6 km) is drawn instead, only in this range, where few of its points are on screen.
_DETAIL_ZOOM = 3.0


def _unit(lonlat: np.ndarray) -> np.ndarray:
    """(n, 2) lon/lat in radians → (n, 3) unit vectors."""
    lon, lat = lonlat[:, 0], lonlat[:, 1]
    return np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], axis=1).astype(np.float32)


class GlobeView(tk.Frame):
    def __init__(self, parent, on_pick=None):
        """on_pick(kind, data): kind = "country" {name, iso, lat, lon} | "satellite" index |
        "radio" index | "quake" index | "plane" index."""
        super().__init__(parent, bg=theme.BG)
        # A plain native window the frames are copied into; on_intro_done is called when the opening
        # animation ends (the main window moves it back from full window to its place).
        self.surface = tk.Frame(self, bg=theme.BG, width=1, height=1)
        self.surface.pack(fill=tk.BOTH, expand=True)
        self._view: tk.Widget = self.surface          # where frames are drawn: the surface, or a full-window one
        self._gdi = gdi.Surface()
        # One OpenGL painter per window drawn into (None: OpenGL could not start there, GDI draws).
        self._painters: dict[int, globe_gl.GlobePainter | None] = {}
        self._batch: globe_gl.GlobePainter | None = None   # set while a frame goes to the GPU
        self._ink = self._gdi                         # what the marks (circles, lines, labels) go to
        self._bounds = (0, 0)
        self._shown_box = None
        self.on_intro_done = None
        self.on_pick = on_pick
        data = world.load()
        self._land, self._border = _unit(data["land"]), _unit(data["border"])
        self._outline = None                          # detailed outline, loaded in the background on start
        self._outline_thread: threading.Thread | None = None
        self.lon0, self.lat0, self.zoom = math.radians(-50.0), math.radians(-15.0), 1.0   # starts over Brazil
        self._target = None
        self._spin = True
        self.layers = {"satellites": True, "quakes": True, "radios": False, "planes": False}
        self.tracker: planes_mod.Tracker | None = None
        self._moved_at = time.monotonic()            # last drag, wheel or turn: the view is "settled" after
        self.sat_kinds: set[str] | None = None        # None = all
        self.satellites = None
        self._sat_pos = None                          # (unit vectors * radius ratio, valid)
        self._sat_time = 0.0
        self.radios: list[dict] = []
        self._radio_vec = np.zeros((0, 3), np.float32)
        self.quakes: list[dict] = []
        self.selected: tuple[str, int] | None = None
        self._screen = {}                             # kind → (x, y, visible) of the last frame, for clicks
        self._size = (0, 0)
        self._dist = None                             # each pixel's distance from the centre, per window size
        self._origin = (0, 0)                         # window position of the drawn image (always 0, 0)
        self._scale = 1                               # drawn at 1/scale of the window, stretched on screen
        self._job = None
        self._last_tick = None
        self._intro_t0: float | None = None
        self._zoom_goal: float | None = None           # where the wheel is taking the zoom
        self._fade = 1.0
        self._stats: list[tuple[float, float]] = []   # (ms between frames, ms drawing), logged every 5 s
        self._stats_t = time.perf_counter()
        self._drag = None
        # PyOpenGL takes ~0.2 s to import: done in the background now, not when the monitor opens.
        threading.Thread(target=lambda: __import__("OpenGL.GL"), daemon=True, name="opengl-import").start()
        self.surface.bind("<ButtonPress-1>", self._press)
        self.surface.bind("<B1-Motion>", self._move)
        self.surface.bind("<ButtonRelease-1>", self._release)
        self.surface.bind("<MouseWheel>", self._wheel)
        self.surface.bind("<Configure>", lambda _e: self._forget_screen())

    def show_on(self, widget: tk.Widget | None) -> None:
        """Draws the frames into widget (the full-window one of the opening; at half resolution when
        GDI draws) or, with None, back into the globe's own place."""
        if self._view is not self.surface:            # the opening's window is about to go
            self._release_painter(self._view)
        self._view = widget or self.surface
        self._scale = 1 if widget is None else _INTRO_SCALE
        self._forget_screen()

    def _forget_screen(self) -> None:
        self._shown_box = None                        # repaint everything on the next frame

    def _painter(self) -> "globe_gl.GlobePainter | None":
        hwnd = self._view.winfo_id()
        if hwnd not in self._painters:
            try:
                painter = globe_gl.GlobePainter(hwnd, theme.BG, theme.GLOBE_SPHERE, theme.CYAN)
                log.info("[Globe] drawn by the GPU: %s", painter.renderer)
            except globe_gl.GLUnavailable as e:
                painter = None
                log.warning("[Globe] OpenGL unavailable (%s): drawing with GDI", e)
            self._painters[hwnd] = painter
        return self._painters[hwnd]

    def _release_painter(self, widget: tk.Widget) -> None:
        try:
            painter = self._painters.pop(widget.winfo_id(), None)
        except tk.TclError:                           # already destroyed
            return
        if painter is not None:
            painter.release()

    def destroy(self) -> None:
        for painter in self._painters.values():
            if painter is not None:
                painter.release()
        self._painters = {}
        self._gdi.release()
        super().destroy()

    # ── data ──

    def set_satellites(self, satellites) -> None:
        self.satellites, self._sat_time, self._sat_pos = satellites, 0.0, None
        self._sat_colors = np.stack([_SAT[k] for k in satellites.kinds]) if len(satellites) else None

    def set_radios(self, radios: list[dict]) -> None:
        self.radios = radios
        lonlat = np.radians(np.array([[r["lon"], r["lat"]] for r in radios], dtype=np.float32)).reshape(-1, 2)
        self._radio_vec = _unit(lonlat) if len(radios) else np.zeros((0, 3), np.float32)

    def set_quakes(self, quakes: list[dict]) -> None:
        self.quakes = quakes

    def focus(self, lat: float, lon: float) -> None:
        """Turns smoothly until (lat, lon) in degrees is in the centre."""
        self._target = (math.radians(lon), math.radians(lat))
        self._spin = False

    # ── loop ──

    def start(self) -> None:
        if self._outline is None and self._outline_thread is None:
            # 809 ms the first time it was needed, in the middle of a zoom: load it before that.
            self._outline_thread = threading.Thread(target=self._load_outline, daemon=True)
            self._outline_thread.start()
        if self._job is None:
            self._last_tick = None
            gdi.fine_timer(True)
            self._job = self.after(1, self._tick)

    def _load_outline(self) -> None:
        self._outline = _unit(world.outline())

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
            gdi.fine_timer(False)

    def intro(self) -> None:
        """The opening animation: zooms out from close to the surface to the whole globe. Its clock
        starts on the first frame drawn: started on the click, a slow first frame (156 ms at
        3440x1369) ate the animation."""
        self._intro_t0 = time.perf_counter()
        self._intro_waiting = True
        self._target, self._spin = None, True
        self.zoom, self._fade = _INTRO_ZOOM, 0.15

    def _end_intro(self) -> None:
        self._intro_t0, self._fade = None, 1.0

    def _tick(self) -> None:
        self._job = None
        if not self._view.winfo_ismapped():
            # Not on screen yet (just gridded) or covered: check again shortly. stop() is what
            # ends the loop when the monitor closes. Returning here for good left the globe black.
            self._last_tick = None
            self._job = self.after(250, self._tick)
            return
        started = time.perf_counter()                 # monotonic() moves in 15.6 ms steps on Windows
        dt = min(0.1, started - self._last_tick) if self._last_tick is not None else _FPS_MS / 1000
        self._last_tick = started
        if self._zoom_goal is not None:
            self._moved_at = time.monotonic()
            step = math.log(self._zoom_goal / self.zoom) * (1 - 0.65 ** (dt * 30))   # ~0.15 s to get there
            self.zoom *= math.exp(step)
            if abs(math.log(self._zoom_goal / self.zoom)) < 0.002:
                self.zoom, self._zoom_goal = self._zoom_goal, None
        if self._intro_t0 is not None:
            if getattr(self, "_intro_waiting", False):
                self._intro_t0, self._intro_waiting = started, False
            self._step_intro(started, dt)
        elif self._target is not None:
            self._moved_at = time.monotonic()
            lon_t, lat_t = self._target
            d_lon = (lon_t - self.lon0 + math.pi) % (2 * math.pi) - math.pi
            k = 1 - 0.85 ** (dt * 30)                # the same easing at any frame rate
            self.lon0 += d_lon * k
            self.lat0 += (lat_t - self.lat0) * k
            if abs(d_lon) < 1e-3 and abs(lat_t - self.lat0) < 1e-3:
                self._target = None
        elif self._spin and self._drag is None and self.zoom < planes_mod.MIN_ZOOM:
            self.lon0 += _SPIN_PER_S * dt            # zoomed in it would keep moving the planes' region
        self.render()
        spent_ms = (time.perf_counter() - started) * 1000
        self._job = self.after(max(1, round(_FPS_MS - spent_ms)), self._tick)
        self._note_frame(dt * 1000, spent_ms, started)

    def _note_frame(self, gap_ms: float, spent_ms: float, now: float) -> None:
        """Frame rate as it really is in the app (window size, other animations), every 5 s."""
        self._stats.append((gap_ms, spent_ms))
        if now - self._stats_t < 5:
            return
        gaps, spent = [g for g, _ in self._stats], [d for _, d in self._stats]
        log.info("[Globe] %.0f frames/s; drawing median %.0f ms, p90 %.0f ms; gap between frames p90 %.0f ms; %dx%d px%s",
                 len(gaps) / (now - self._stats_t), statistics.median(spent),
                 statistics.quantiles(spent, n=10)[-1] if len(spent) > 1 else spent[0],
                 statistics.quantiles(gaps, n=10)[-1] if len(gaps) > 1 else gaps[0],
                 self._view.winfo_width(), self._view.winfo_height(),
                 "; dragging" if self._drag is not None else "")
        self._stats, self._stats_t = [], now

    def _step_intro(self, now: float, dt: float) -> None:
        p = min(1.0, (now - self._intro_t0) / _INTRO_S)
        ease = 1 - (1 - p) ** 3                       # fast at first, gently settling
        self.zoom = math.exp(math.log(_INTRO_ZOOM) * (1 - ease))
        self.lon0 += _SPIN_PER_S * 6 * (1 - ease) * dt   # a quicker turn that slows down with the zoom
        self._fade = min(1.0, 0.15 + p / 0.45)        # the points fade in during the first part
        self._moved_at = time.monotonic()
        if p >= 1:
            self.zoom, self._fade, self._intro_t0 = 1.0, 1.0, None
            if self.on_intro_done is not None:
                self.on_intro_done()

    # ── projection ──

    def _rotation(self) -> np.ndarray:
        """World unit vectors → view: x right, y up, z towards the viewer."""
        cl, sl = math.cos(self.lon0), math.sin(self.lon0)
        ca, sa = math.cos(self.lat0), math.sin(self.lat0)
        yaw = np.array([[cl, 0, -sl], [0, 1, 0], [sl, 0, cl]], np.float32)       # brings lon0 to the front
        pitch = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]], np.float32)    # brings lat0 to the centre
        return pitch @ yaw

    def _geometry(self):
        w, h = self._view.winfo_width() // self._scale, self._view.winfo_height() // self._scale
        radius = 0.42 * min(w, h) * self.zoom
        return w, h, radius, w / 2, h / 2

    @staticmethod
    def _shading_lut() -> np.ndarray:
        """Background colour by distance from the centre in radii (0..2): the shaded sphere and its glow."""
        d = np.linspace(0, 2, _LUT_SIZE, dtype=np.float32)
        lut = np.tile(_BG, (_LUT_SIZE, 1))
        inside = d < 1
        lut[inside] = _SPHERE * (0.55 + 0.45 * np.sqrt(1 - d[inside] ** 2))[:, None] + _BG * 0.2
        glow = np.clip(1 - np.abs(d - 1) * 14, 0, 1) * 0.55 + np.clip(1 - (d - 1) * 3, 0, 1) * (d > 1) * 0.12
        lut += glow[:, None] * _LAND * 0.45
        return np.clip(lut, 0, 255).astype(np.uint8)

    def _background(self, w: int, h: int, radius: float, cx: float, cy: float,
                    box: tuple[int, int, int, int] | None = None) -> np.ndarray:
        """The background of box = (x0, y0, x1, y1) of the window (all of it by default), looked up
        from each pixel's distance, worked out once per window size: changing the zoom recomputed the
        whole sphere and took ~140 ms a frame while the wheel turned (2026-11-07)."""
        if self._dist is None or self._dist.shape != (h, w):
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            self._dist = np.hypot(xx - cx, yy - cy)
            self._lut = self._shading_lut()
        x0, y0, x1, y1 = box or (0, 0, w, h)
        dist = self._dist[y0:y1, x0:x1]
        if getattr(self, "_scaled", None) is None or self._scaled.shape != dist.shape:
            # Reused buffers: with np.take into them a new zoom costs ~6 ms instead of ~14 ms.
            self._scaled = np.empty(dist.shape, np.float32)
            self._index = np.empty(dist.shape, np.int32)
            self._bg_buf = np.empty((*dist.shape, 3), np.uint8)
        np.multiply(dist, (_LUT_SIZE - 1) / (2 * max(radius, 1)), out=self._scaled)
        np.add(self._scaled, 0.5, out=self._scaled)                     # nearest entry, not the one below
        np.minimum(self._scaled, _LUT_SIZE - 1, out=self._scaled)
        self._index[:] = self._scaled
        return np.take(self._lut, self._index, axis=0, out=self._bg_buf)

    def _plot(self, img, x, y, color, strength, glow=True):
        """Points into the uint8 image by flat index (faster than 2-D fancy indexing), with a halo on
        the four neighbours. When two points land on the same pixel one wins, which does not show."""
        h, w = img.shape[:2] if self._batch is None else self._bounds[::-1]
        ox, oy = self._origin                         # window coordinates → the drawn square's
        x, y = (x - ox).astype(np.int32), (y - oy).astype(np.int32)
        ok = (x > 0) & (x < w - 1) & (y > 0) & (y < h - 1)
        flat = y[ok] * w + x[ok]
        # The opening animation fades the points in, not the whole picture: darkening every pixel cost
        # 15 ms a frame at 2330x926, while each point's strength is already there.
        strength = np.broadcast_to(np.asarray(strength, np.float32) * self._fade, ok.shape)[ok][:, None]
        c = np.minimum((color[None, :] if color.ndim == 1 else color[ok]) * strength, 255)
        if self._batch is not None:                   # to the GPU, all at once when the frame ends
            self._batch.points(x[ok], y[ok], c, glow)
            return
        pixels = img.reshape(-1, 3)
        if glow:
            halo = (c * 0.35).astype(np.uint8)
            for off in (1, -1, w, -w):
                pixels[flat + off] = np.maximum(pixels[flat + off], halo)
        pixels[flat] = np.maximum(pixels[flat], c.astype(np.uint8))

    def render(self) -> None:
        if self._view.winfo_width() < 20 or self._view.winfo_height() < 20:
            return
        painter = self._painter()
        if painter is not None:
            self._scale = 1
        elif self._view is not self.surface:
            self._scale = _INTRO_SCALE
        w, h, radius, cx, cy = self._geometry()
        if w < 20 or h < 20:
            return
        if painter is not None:
            self._render_gpu(painter, w, h, radius, cx, cy)
            return
        self._batch, self._ink = None, self._gdi
        box = (0, 0, w, h)        # the whole view: satellites far from the Earth show at the sides
        if (w, h, round(radius), box) != self._size:
            # While the zoom keeps changing, the previous background is kept if the globe still fits
            # in its square (always, zoomed in: the square is the whole window) and its edge is off by
            # little: 4%, or 30% in the opening animation (fast, and the sphere still covers the window). Once the zoom stops,
            # the exact one is made. (At 2330x926 every zoom frame redrew it: 45-55 ms.)
            old_w, old_h, old_radius, old_box = self._size if len(self._size) == 4 else (0, 0, 0, None)
            slack = 1.3 if self._intro_t0 is not None else 1.04
            fits = old_box is not None and old_box[0] <= box[0] and old_box[1] <= box[1] \
                and old_box[2] >= box[2] and old_box[3] >= box[3]
            moving = radius != getattr(self, "_last_radius", radius)
            if (old_w, old_h) == (w, h) and fits and moving and 1 / slack < radius / max(old_radius, 1) < slack:
                box = old_box
            else:
                # A new zoom only needs a new background; the Tk image is rebuilt below only when the
                # square's size changes (rebuilding it on every wheel step was part of the zoom stutter).
                self._size = (w, h, round(radius), box)
                self._bg = self._background(w, h, radius, cx, cy, box)
        self._last_radius = radius
        self._origin = box[:2]
        img = self._bg.copy()
        rot = self._draw_layers(img, radius, cx, cy)
        if self._gdi.resize(w, h) or box != self._shown_box:
            self._gdi.fill(_BG)                       # outside the square: background, painted once
            self._shown_box = box
        self._gdi.put(img, *box[:2])
        self._draw_overlay(rot, radius, cx, cy)
        self._gdi.present(self._view.winfo_id(), self._scale)

    def _render_gpu(self, painter, w, h, radius, cx, cy) -> None:
        """The same layers and marks, sent to the graphics card; it draws the sphere's shading too."""
        self._batch, self._ink, self._bounds, self._origin = painter, painter, (w, h), (0, 0)
        painter.begin(w, h, radius, cx, cy)
        rot = self._draw_layers(None, radius, cx, cy)
        self._draw_overlay(rot, radius, cx, cy)
        painter.present()

    def _draw_layers(self, img, radius, cx, cy) -> np.ndarray:
        """Land, borders, radios, satellites and planes, into img (GDI) or the GPU batch."""
        rot = self._rotation()
        border = self._border
        if self.zoom >= _DETAIL_ZOOM and self._outline is not None:   # the coarse one until it has loaded
            border = self._outline
        for vecs, color, base in ((self._land, _LAND, 0.95), (border, _BORDER, 1.0)):
            v = vecs @ rot.T
            front = v[:, 2] > 0
            v = v[front]
            self._plot(img, cx + radius * v[:, 0], cy - radius * v[:, 1], color, base * (0.4 + 0.6 * v[:, 2]))
        self._screen = {}
        if self.layers["radios"] and len(self._radio_vec):
            v = self._radio_vec @ rot.T
            vis = v[:, 2] > 0
            sx, sy = cx + radius * v[:, 0], cy - radius * v[:, 1]
            self._plot(img, sx[vis], sy[vis], _RADIO, np.full(int(vis.sum()), 0.9))
            self._screen["radio"] = (sx, sy, vis)
        if self.layers["satellites"] and self.satellites is not None and len(self.satellites):
            self._draw_satellites(img, rot, radius, cx, cy)
        if self.layers["planes"] and self.tracker is not None and len(self.tracker):
            self._draw_planes(img, rot, radius, cx, cy)
        return rot

    def _draw_satellites(self, img, rot, radius, cx, cy) -> None:
        import time
        now = time.monotonic()
        if self._sat_pos is None or now - self._sat_time > _SAT_REFRESH_S:
            lat, lon, alt, ok = self.satellites.positions()
            scale = (1 + alt / 6371.0).astype(np.float32)
            vec = np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], axis=1) * scale[:, None]
            self._sat_pos, self._sat_alt, self._sat_time = (vec.astype(np.float32), ok), alt, now
        vec, ok = self._sat_pos
        if self.sat_kinds is not None:
            ok = ok & np.isin(self.satellites.kinds, list(self.sat_kinds))
        v = vec @ rot.T
        # Hidden only when behind the Earth: in front of it, or outside the disk, it shows.
        vis = ok & ((v[:, 2] > 0) | (v[:, 0] ** 2 + v[:, 1] ** 2 > 1))
        sx, sy = cx + radius * v[:, 0], cy - radius * v[:, 1]
        # Over the Earth they are dimmer, so the land stays readable; at the edge, the bright halo.
        over_disk = v[vis, 0] ** 2 + v[vis, 1] ** 2 < 1
        self._plot(img, sx[vis], sy[vis], self._sat_colors[vis], np.where(over_disk, 0.45, 1.0))
        self._screen["satellite"] = (sx, sy, vis)

    def _project(self, lat, lon, rot, radius, cx, cy):
        v = _unit(np.radians(np.stack([lon, lat], axis=1)).astype(np.float32)) @ rot.T
        return cx + radius * v[:, 0], cy - radius * v[:, 1], v[:, 2] > 0

    def _draw_planes(self, img, rot, radius, cx, cy) -> None:
        """Trails fading from new to old, then each plane: a 5-pixel mark and a 3-pixel stroke ahead."""
        t_lat, t_lon, age = self.tracker.trails()
        if len(t_lat):
            sx, sy, vis = self._project(t_lat, t_lon, rot, radius, cx, cy)
            self._plot(img, sx[vis], sy[vis], _PLANE, 0.15 + 0.45 * (1 - age[vis]), glow=False)
        lat, lon, track = self.tracker.positions(time.monotonic())
        sx, sy, vis = self._project(lat, lon, rot, radius, cx, cy)
        ax, ay, _ = self._project(*planes_mod.advance(lat, lon, track, 1.0), rot, radius, cx, cy)
        dx, dy = ax - sx, ay - sy
        norm = np.maximum(np.hypot(dx, dy), 1e-6)
        dx, dy = dx / norm, dy / norm
        x, y = sx[vis], sy[vis]
        full = np.ones(int(vis.sum()))
        for ox, oy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            self._plot(img, x + ox, y + oy, _PLANE, full, glow=False)
        for k in (2, 3, 4):
            self._plot(img, x + dx[vis] * k, y + dy[vis] * k, _PLANE, full * 0.9, glow=False)
        self._screen["plane"] = (sx, sy, vis)

    def _draw_overlay(self, rot, radius, cx, cy) -> None:
        """Earthquakes (sized by magnitude), the ISS and the selection, drawn on the frame."""
        g = self._ink
        if self.layers["quakes"] and self.quakes:
            ll = np.radians(np.array([[q["lon"], q["lat"]] for q in self.quakes], np.float32))
            v = _unit(ll) @ rot.T
            sx, sy = cx + radius * v[:, 0], cy - radius * v[:, 1]
            for i, q in enumerate(self.quakes):
                if v[i, 2] > 0:
                    g.ellipse(sx[i], sy[i], 2 + max(0.0, q["mag"] - 2.5) * 2.4, theme.DANGER, 1)
            self._screen["quake"] = (sx, sy, v[:, 2] > 0)
        if "satellite" in self._screen and self.satellites is not None:
            iss = self.satellites.find("ISS (ZARYA)")
            sx, sy, vis = self._screen["satellite"]
            if iss is not None and vis[iss]:
                g.ellipse(sx[iss], sy[iss], 5, theme.SAT_STATION, 2)
                g.text(sx[iss] + 8, sy[iss], "ISS", theme.SAT_STATION, theme.px(12))
        if self.selected is not None and self.selected[0] == "plane" and "plane" in self._screen:
            self._draw_selected_plane(rot, radius, cx, cy)
        elif self.selected is not None and self.selected[0] in self._screen:
            kind, i = self.selected
            sx, sy, vis = self._screen[kind]
            if i < len(vis) and vis[i]:
                g.ellipse(sx[i], sy[i], 8, theme.TEXT, 2)

    def _draw_selected_plane(self, rot, radius, cx, cy) -> None:
        i = self.tracker.index(self.selected[1]) if self.tracker is not None else None
        sx, sy, vis = self._screen["plane"]
        if i is None or i >= len(vis) or not vis[i]:
            return
        lat, lon, track = self.tracker.positions(time.monotonic())
        info = self.tracker.get(i)
        km = (info.get("speed_kt") or 0) * planes_mod.KNOT_KM_S * 60 * _HEADING_MIN
        if km > 0:
            steps = np.linspace(0, km, 12)
            la, lo = planes_mod.advance(np.full(12, lat[i]), np.full(12, lon[i]), np.full(12, track[i]), steps)
            px, py, front = self._project(la, lo, rot, radius, cx, cy)
            if front.all():
                self._ink.polyline(np.column_stack([px, py]), theme.PEACH, dashed=True)
        self._ink.ellipse(sx[i], sy[i], 7, theme.TEXT, 2)

    def settled_s(self) -> float:
        """Seconds since the view last moved (drag, wheel or a turn towards a place)."""
        return 0.0 if self._drag is not None else time.monotonic() - self._moved_at

    def center(self) -> tuple[float, float]:
        """(lat, lon) in degrees at the centre of the view."""
        return math.degrees(self.lat0), (math.degrees(self.lon0) + 540) % 360 - 180

    # ── mouse ──

    def _press(self, e) -> None:
        self._drag = (e.x, e.y, False)

    def _move(self, e) -> None:
        if self._drag is None:
            return
        self._end_intro()                            # dragging during the opening ends it
        x0, y0, _ = self._drag
        _w, _h, radius, _cx, _cy = self._geometry()
        self.lon0 -= (e.x - x0) / max(radius, 1)
        self.lat0 = max(-1.4, min(1.4, self.lat0 + (e.y - y0) / max(radius, 1)))
        self._drag = (e.x, e.y, True)
        self._target, self._spin = None, False
        self._moved_at = time.monotonic()

    def _release(self, e) -> None:
        moved = self._drag is not None and self._drag[2]
        self._drag = None
        if moved or self.on_pick is None:
            return
        for kind in ("plane", "satellite", "radio", "quake"):  # the closest point within 7 px wins
            if kind in self._screen:
                sx, sy, vis = self._screen[kind]
                d = np.where(vis, (sx - e.x) ** 2 + (sy - e.y) ** 2, np.inf)
                if len(d) and d.min() <= 49:
                    i = int(d.argmin())
                    # A plane is kept by its transponder code: its index changes with every update.
                    self.selected = (kind, self.tracker.hexes[i] if kind == "plane" else i)
                    self.on_pick(kind, i)
                    return
        hit = self.screen_to_latlon(e.x, e.y)
        if hit is None:
            return
        lat, lon = hit
        country = world.country_at(lat, lon)
        self.selected = None
        self.on_pick("country", {**(country or {"name": "", "iso": ""}), "lat": lat, "lon": lon})

    def _wheel(self, e) -> None:
        """Sets where the zoom is going; the frames glide there. A 12% jump in one frame looked like a
        dropped frame and forced a whole new background (45-55 ms at 2330x926)."""
        goal = self._zoom_goal if self._zoom_goal is not None else self.zoom
        self._zoom_goal = max(0.6, min(_MAX_ZOOM, goal * (1.12 if e.delta > 0 else 1 / 1.12)))
        self._end_intro()                            # the user took over
        self._moved_at = time.monotonic()

    def zoom_to(self, zoom: float) -> None:
        self.zoom, self._zoom_goal = max(0.6, min(_MAX_ZOOM, zoom)), None
        self._moved_at = time.monotonic()

    def screen_to_latlon(self, x: float, y: float):
        _w, _h, radius, cx, cy = self._geometry()
        px, py = (x - cx) / radius, -(y - cy) / radius
        if px * px + py * py >= 1:
            return None
        pz = math.sqrt(1 - px * px - py * py)
        wx, wy, wz = self._rotation().T @ np.array([px, py, pz], np.float32)
        return math.degrees(math.asin(max(-1, min(1, wy)))), math.degrees(math.atan2(wx, wz))
