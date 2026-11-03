"""Orb: a sphere of light with a wave around it that follows the real voice volume.

It was the old sphere (the face's fallback). Drawn with vector canvas items:
0.7 ms per frame versus 11 ms for the face.
"""

import math
import random
import tkinter as tk

from pidreams.ui import theme
from pidreams.ui.appearances.base import Appearance
from pidreams.ui.widgets import _blend

_GRID = theme.blend(theme.BORDER, 0.35)   # faint over the glass
_WAVE_POINTS = 72
_MAX_WAVE = 16.0      # px of amplitude with the voice at its peak


class OrbCanvas(Appearance):
    MAX_SIZE = 800      # 14% of a core speaking at 800 px (measured 2026-10-31)
    def __init__(self, parent, size: int = 300, bg: str = theme.GLASS, on_fail=None):
        super().__init__(parent, size, size, bg, on_fail)
        self.size = size
        self.cx = self.cy = size // 2
        self.radius = size // 2 - 62          # rings reach radius+58: they fit in the frame
        self._phase = 0.0
        self._rings: list = []
        self._last_ring = 0.0
        self._particles = [{
            "angle": random.uniform(0, 2 * math.pi),
            "r": self.radius + random.randint(8, 50),
            "speed": random.uniform(0.004, 0.018) * random.choice((1, -1)),
            "sz": random.randint(1, 3),
            "phase_offset": random.uniform(0, math.pi * 2),
        } for _ in range(18)]

    def _frame_holder(self):
        self._phase += 0.035
        if self.state == "speaking" and self.voice > 0.25 and self._phase - self._last_ring > 0.25:
            self._rings.append({"r": self.radius * 0.85, "alpha": 0.4 + 0.5 * self.voice})
            self._last_ring = self._phase
        self.delete("all")
        self._draw_grid()
        self._draw_expanding_rings()
        self._draw_decorative_rings()
        self._draw_wave()
        self._draw_sphere()
        self._draw_particles()
        if self.state == "listening":
            self._draw_scan()

    def _draw_grid(self):
        step = 28 * self.size / 300          # same number of lines at any size
        for x in (i * step for i in range(int(self.size / step) + 2)):
            self.create_line(x, 0, x, self.size, fill=_GRID, width=1)
        for y in (i * step for i in range(int(self.size / step) + 2)):
            self.create_line(0, y, self.size, y, fill=_GRID, width=1)

    def _draw_wave(self):
        """Wavy outline: nearly still at rest, it rises and falls with the syllables."""
        ph = self._phase
        amp = 1.0 + _MAX_WAVE * self.voice if self.state == "speaking" else 1.0
        if self.state == "thinking":
            amp = 3.0
        base = self.radius + 14
        points = []
        for i in range(_WAVE_POINTS):
            a = 2 * math.pi * i / _WAVE_POINTS
            r = base + amp * (0.6 * math.sin(5 * a + ph * 3.0) + 0.4 * math.sin(9 * a - ph * 4.3))
            points += (self.cx + r * math.cos(a), self.cy + r * math.sin(a))
        glow = 0.35 + 0.6 * self.voice if self.state == "speaking" else 0.3
        self.create_polygon(points, outline=_blend(0, 210, 255, glow), fill="", width=2, smooth=True)

    def _draw_sphere(self):
        ph = self._phase
        if self.state == "speaking":
            pulse = 1.0 + 0.10 * self.voice
        elif self.state == "listening":
            pulse = 1.0 + 0.025 * math.sin(ph * 1.5)
        elif self.state == "thinking":
            pulse = 1.0 + 0.06 * math.sin(ph * 2.5)
        else:
            pulse = 1.0 + 0.015 * math.sin(ph * 0.8)

        r = self.radius * pulse
        layers = [
            (1.00,   0,  30,  80, 0.12),
            (0.90,   0,  60, 140, 0.28),
            (0.78,   0,  90, 190, 0.48),
            (0.65,   0, 130, 215, 0.65),
            (0.50,   0, 160, 235, 0.80),
            (0.35,  20, 190, 250, 0.90),
            (0.20,  80, 215, 255, 0.95),
            (0.09, 160, 235, 255, 1.00),
        ]
        boost = 1.0 + 0.3 * self.voice if self.state == "speaking" else 1.0
        for frac, cr, cg, cb, alpha in layers:
            rad = r * frac
            color = _blend(int(cr * boost), int(cg), int(cb), min(1.0, alpha * boost))
            self.create_oval(self.cx - rad, self.cy - rad, self.cx + rad, self.cy + rad,
                             fill=color, outline="")
        hx, hy, hr = self.cx - r * 0.28, self.cy - r * 0.28, r * 0.14
        self.create_oval(hx - hr, hy - hr, hx + hr, hy + hr,
                         fill=_blend(200, 240, 255, 0.85), outline="")

    def _draw_decorative_rings(self):
        for idx, off in enumerate([28, 42, 58]):
            r = self.radius + off
            alpha = 0.12 + 0.08 * math.sin(self._phase + idx * 1.1)
            if self.state == "speaking":
                alpha *= 2.2
            elif self.state == "listening":
                alpha *= 1.4
            self.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r,
                             outline=_blend(0, 180, 255, min(1.0, alpha)), fill="", width=1)
        if self.state in ("listening", "thinking"):
            arc_r = self.radius + 48
            speed = 45 if self.state == "listening" else 80
            start = (self._phase * speed) % 360
            extent = 55 if self.state == "listening" else 100
            for offset in (0, 180):
                self.create_arc(self.cx - arc_r, self.cy - arc_r, self.cx + arc_r, self.cy + arc_r,
                                start=start + offset, extent=extent,
                                outline=_blend(0, 190, 255, 0.75), fill="", width=2, style=tk.ARC)

    def _draw_expanding_rings(self):
        alive = []
        for ring in self._rings:
            ring["r"] += 3.0
            ring["alpha"] -= 0.022
            if ring["alpha"] > 0:
                r = ring["r"]
                self.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r,
                                 outline=_blend(0, 210, 255, ring["alpha"]), fill="", width=2)
                alive.append(ring)
        self._rings = alive

    def _draw_particles(self):
        for p in self._particles:
            p["angle"] += p["speed"]
            x = self.cx + p["r"] * math.cos(p["angle"])
            y = self.cy + p["r"] * math.sin(p["angle"])
            if not (0 <= x <= self.size and 0 <= y <= self.size):
                continue
            s = p["sz"]
            intensity = 0.4 + 0.5 * math.sin(self._phase + p["phase_offset"])
            if self.state == "speaking":
                intensity = min(1.0, intensity * (1.0 + 0.6 * self.voice))
            self.create_oval(x - s, y - s, x + s, y + s,
                             fill=_blend(0, 200, 255, intensity), outline="")

    def _draw_scan(self):
        scan_y = self.cy + int(self.radius * 0.88 * math.sin(self._phase * 2.2))
        self.create_line(self.cx - self.radius, scan_y, self.cx + self.radius, scan_y,
                         fill=_blend(0, 220, 255, 0.18), width=1)
