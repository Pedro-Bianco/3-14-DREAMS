"""The monitor's 3D globe: orthographic projection painted with numpy into one opaque image.

Measured with 10 000 points (2026-11-02): one Canvas item per point 218 ms per frame, an RGBA
image 1751 ms, an opaque image 7.4 ms. So land, borders, satellites and radios are pixels of a
single image; only the few earthquake marks and the selection are Canvas items on top. Nothing
runs while the view is hidden. No GPU.
"""

import math
import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

from pidreams.monitor import world
from pidreams.ui import theme

_FPS_MS = 40                          # ~25 frames/s while visible
_SPIN = math.radians(2.0) * _FPS_MS / 1000     # slow idle spin: 2° per second
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


def _unit(lonlat: np.ndarray) -> np.ndarray:
    """(n, 2) lon/lat in radians → (n, 3) unit vectors."""
    lon, lat = lonlat[:, 0], lonlat[:, 1]
    return np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], axis=1).astype(np.float32)


class GlobeView(tk.Frame):
    def __init__(self, parent, on_pick=None):
        """on_pick(kind, data): kind = "country" {name, iso, lat, lon} | "satellite" index |
        "radio" index | "quake" index."""
        super().__init__(parent, bg=theme.BG)
        self.canvas = tk.Canvas(self, bg=theme.BG, highlightthickness=0, width=1, height=1)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.on_pick = on_pick
        data = world.load()
        self._land, self._border = _unit(data["land"]), _unit(data["border"])
        self.lon0, self.lat0, self.zoom = math.radians(-50.0), math.radians(-15.0), 1.0   # starts over Brazil
        self._target = None
        self._spin = True
        self.layers = {"satellites": True, "quakes": True, "radios": False}
        self.sat_kinds: set[str] | None = None        # None = all
        self.satellites = None
        self._sat_pos = None                          # (unit vectors * radius ratio, valid)
        self._sat_time = 0.0
        self.radios: list[dict] = []
        self._radio_vec = np.zeros((0, 3), np.float32)
        self.quakes: list[dict] = []
        self.selected: tuple[str, int] | None = None
        self._photo = None
        self._image_item = self.canvas.create_image(0, 0, anchor="nw")
        self._overlay: list[int] = []
        self._screen = {}                             # kind → (x, y, visible) of the last frame, for clicks
        self._size = (0, 0)
        self._job = None
        self._drag = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._wheel)

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
        if self._job is None:
            self._job = self.after(_FPS_MS, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _tick(self) -> None:
        self._job = None
        if not self.winfo_ismapped():
            # Not on screen yet (just gridded) or covered: check again shortly. stop() is what
            # ends the loop when the monitor closes. Returning here for good left the globe black.
            self._job = self.after(250, self._tick)
            return
        if self._target is not None:
            lon_t, lat_t = self._target
            d_lon = (lon_t - self.lon0 + math.pi) % (2 * math.pi) - math.pi
            self.lon0 += d_lon * 0.15
            self.lat0 += (lat_t - self.lat0) * 0.15
            if abs(d_lon) < 1e-3 and abs(lat_t - self.lat0) < 1e-3:
                self._target = None
        elif self._spin and self._drag is None:
            self.lon0 += _SPIN
        self.render()
        self.start()

    # ── projection ──

    def _rotation(self) -> np.ndarray:
        """World unit vectors → view: x right, y up, z towards the viewer."""
        cl, sl = math.cos(self.lon0), math.sin(self.lon0)
        ca, sa = math.cos(self.lat0), math.sin(self.lat0)
        yaw = np.array([[cl, 0, -sl], [0, 1, 0], [sl, 0, cl]], np.float32)       # brings lon0 to the front
        pitch = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]], np.float32)    # brings lat0 to the centre
        return pitch @ yaw

    def _geometry(self):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        radius = 0.42 * min(w, h) * self.zoom
        return w, h, radius, w / 2, h / 2

    def _background(self, w: int, h: int, radius: float, cx: float, cy: float) -> np.ndarray:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(radius, 1)
        img = np.empty((h, w, 3), np.float32)
        img[:] = _BG
        inside = d < 1
        img[inside] = _SPHERE * (0.55 + 0.45 * np.sqrt(1 - d[inside] ** 2))[:, None] + _BG * 0.2
        glow = np.clip(1 - np.abs(d - 1) * 14, 0, 1) * 0.55 + np.clip(1 - (d - 1) * 3, 0, 1) * (d > 1) * 0.12
        img += glow[..., None] * _LAND * 0.45
        return img

    def _plot(self, img, x, y, color, strength, glow=True):
        h, w = img.shape[:2]
        x, y = x.astype(np.int32), y.astype(np.int32)
        ok = (x > 0) & (x < w - 1) & (y > 0) & (y < h - 1)
        x, y, strength = x[ok], y[ok], strength[ok][:, None]
        c = (color[None, :] if color.ndim == 1 else color[ok]) * strength
        # Plain fancy assignment (np.maximum.at was the slowest part of a frame): when two
        # points land on the same pixel one of them wins, which does not show.
        if glow:
            halo = c * 0.35
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                img[y + dy, x + dx] = np.maximum(img[y + dy, x + dx], halo)
        img[y, x] = np.maximum(img[y, x], c)

    def render(self) -> None:
        w, h, radius, cx, cy = self._geometry()
        if w < 20 or h < 20:
            return
        if (w, h, round(radius)) != self._size:
            self._size = (w, h, round(radius))
            self._bg = self._background(w, h, radius, cx, cy)
            self._photo = None
        img = self._bg.copy()
        rot = self._rotation()
        for vecs, color, base in ((self._land, _LAND, 0.95), (self._border, _BORDER, 1.0)):
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
        out = np.clip(img, 0, 255).astype(np.uint8)
        frame = Image.fromarray(out)
        if self._photo is None or self._photo.width() != w or self._photo.height() != h:
            self._photo = ImageTk.PhotoImage(frame)
            self.canvas.itemconfig(self._image_item, image=self._photo)
        else:
            self._photo.paste(frame)
        self._draw_overlay(rot, radius, cx, cy)

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

    def _draw_overlay(self, rot, radius, cx, cy) -> None:
        """Earthquakes (sized by magnitude), the ISS and the selection, as Canvas items."""
        for item in self._overlay:
            self.canvas.delete(item)
        self._overlay = []
        if self.layers["quakes"] and self.quakes:
            ll = np.radians(np.array([[q["lon"], q["lat"]] for q in self.quakes], np.float32))
            v = _unit(ll) @ rot.T
            sx, sy = cx + radius * v[:, 0], cy - radius * v[:, 1]
            for i, q in enumerate(self.quakes):
                if v[i, 2] <= 0:
                    continue
                r = 2 + max(0.0, q["mag"] - 2.5) * 2.4
                self._overlay.append(self.canvas.create_oval(sx[i] - r, sy[i] - r, sx[i] + r, sy[i] + r,
                                                             outline=theme.DANGER, width=1))
            self._screen["quake"] = (sx, sy, v[:, 2] > 0)
        if "satellite" in self._screen and self.satellites is not None:
            iss = self.satellites.find("ISS (ZARYA)")
            sx, sy, vis = self._screen["satellite"]
            if iss is not None and vis[iss]:
                self._overlay.append(self.canvas.create_oval(sx[iss] - 5, sy[iss] - 5, sx[iss] + 5, sy[iss] + 5,
                                                             outline=theme.SAT_STATION, width=2))
                self._overlay.append(self.canvas.create_text(sx[iss] + 8, sy[iss], text="ISS", anchor="w",
                                                             fill=theme.SAT_STATION, font=theme.FONT_SMALL))
        if self.selected is not None and self.selected[0] in self._screen:
            kind, i = self.selected
            sx, sy, vis = self._screen[kind]
            if i < len(vis) and vis[i]:
                self._overlay.append(self.canvas.create_oval(sx[i] - 8, sy[i] - 8, sx[i] + 8, sy[i] + 8,
                                                             outline=theme.TEXT, width=2))

    # ── mouse ──

    def _press(self, e) -> None:
        self._drag = (e.x, e.y, False)

    def _move(self, e) -> None:
        if self._drag is None:
            return
        x0, y0, _ = self._drag
        _w, _h, radius, _cx, _cy = self._geometry()
        self.lon0 -= (e.x - x0) / max(radius, 1)
        self.lat0 = max(-1.4, min(1.4, self.lat0 + (e.y - y0) / max(radius, 1)))
        self._drag = (e.x, e.y, True)
        self._target, self._spin = None, False

    def _release(self, e) -> None:
        moved = self._drag is not None and self._drag[2]
        self._drag = None
        if moved or self.on_pick is None:
            return
        for kind in ("satellite", "radio", "quake"):          # the closest point within 7 px wins
            if kind in self._screen:
                sx, sy, vis = self._screen[kind]
                d = np.where(vis, (sx - e.x) ** 2 + (sy - e.y) ** 2, np.inf)
                if len(d) and d.min() <= 49:
                    i = int(d.argmin())
                    self.selected = (kind, i)
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
        self.zoom = max(0.6, min(4.0, self.zoom * (1.12 if e.delta > 0 else 1 / 1.12)))

    def screen_to_latlon(self, x: float, y: float):
        _w, _h, radius, cx, cy = self._geometry()
        px, py = (x - cx) / radius, -(y - cy) / radius
        if px * px + py * py >= 1:
            return None
        pz = math.sqrt(1 - px * px - py * py)
        wx, wy, wz = self._rotation().T @ np.array([px, py, pz], np.float32)
        return math.degrees(math.asin(max(-1, min(1, wy)))), math.degrees(math.atan2(wx, wz))
