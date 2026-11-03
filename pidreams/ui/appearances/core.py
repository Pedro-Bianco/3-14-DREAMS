"""Energy core (JARVIS style): a core of light, segmented rings spinning in opposite
directions and a crown of strokes that follows the voice volume.

Only geometric shapes drawn here (no third-party art or logo) and vector canvas items,
for the cost.
"""

import math

from pidreams.ui import theme
from pidreams.ui.appearances.base import Appearance
from pidreams.ui.widgets import _blend

# (radius, segments, opening of each segment in degrees, thickness, direction)
_RINGS = ((72, 3, 80, 3, 1), (96, 8, 30, 2, -1), (118, 2, 140, 4, 1))
_STROKES = 48
# Degrees per frame in each state; speaking adds the voice (see _speed).
_SPEED = {"idle": 0.4, "listening": 1.2, "thinking": 4.0, "speaking": 1.0}
_GLOW = {"idle": 0.6, "listening": 0.9, "thinking": 0.8, "speaking": 0.75}


class CoreCanvas(Appearance):
    MAX_SIZE = 900      # 11% of a core speaking at 900 px (measured 2026-10-31)
    def __init__(self, parent, size: int = 300, bg: str = theme.GLASS, on_fail=None):
        super().__init__(parent, size, size, bg, on_fail)
        self.size = size
        self.c = size / 2
        self.esc = size / 300
        self._spin = 0.0

    def _speed(self) -> float:
        v = _SPEED[self.state]
        return v + 2.0 * self.voice if self.state == "speaking" else v

    def _glow(self) -> float:
        b = _GLOW[self.state]
        if self.state == "speaking":
            return min(1.0, b + 0.4 * self.voice)
        if self.state == "thinking":
            return b + 0.2 * math.sin(self._t * 6.0)
        return b + 0.05 * math.sin(self._t * 1.3)

    def _frame_holder(self):
        self._spin += self._speed()
        glow = self._glow()
        self.delete("all")
        self._crown(glow)
        self._rings(glow)
        self._center(glow)

    def _circle(self, r, **kw):
        c = self.c
        return self.create_oval(c - r, c - r, c + r, c + r, **kw)

    def _center(self, glow: float):
        e = self.esc
        pulse_value = 1.0 + (0.25 * self.voice if self.state == "speaking" else 0.04 * math.sin(self._t * 2.0))
        r0 = 46 * e * pulse_value
        for frac, alpha in ((1.0, 0.25), (0.8, 0.45), (0.62, 0.65), (0.45, 0.85), (0.28, 1.0)):
            self._circle(r0 * frac, fill=_blend(int(120 * frac), 210, 255, alpha * glow), outline="")
        self._circle(r0 * 0.14, fill=_blend(220, 250, 255, glow), outline="")
        self._circle(58 * e, outline=_blend(0, 190, 255, 0.5 * glow), width=1)

    def _rings(self, glow: float):
        for i, (radius, segments, opening, thickness, direction) in enumerate(_RINGS):
            r = radius * self.esc
            c = self.c
            # Pensando, o anel do meio inverte e acelera: "processando".
            direction_now = -direction if self.state == "thinking" and i == 1 else direction
            start_at = (self._spin * direction_now * (1 + 0.35 * i)) % 360
            step = 360 / segments
            for s in range(segments):
                self.create_arc(c - r, c - r, c + r, c + r, start=start_at + s * step, extent=opening,
                                style="arc", outline=_blend(0, 200, 255, glow * (0.9 - 0.15 * i)),
                                width=thickness)

    def _crown(self, glow: float):
        """Radial strokes: short at rest, they grow with the syllables."""
        c, e = self.c, self.esc
        for k in range(_STROKES):
            a = 2 * math.pi * k / _STROKES
            if self.state == "speaking":
                wave = 0.5 + 0.5 * math.sin(self._t * 9.0 + k * 0.9)
                length = 3 + 18 * self.voice * (0.4 + 0.6 * wave)
            else:
                length = 3
            r1 = 132 * e
            r2 = r1 + length * e
            self.create_line(c + r1 * math.cos(a), c + r1 * math.sin(a), c + r2 * math.cos(a),
                             c + r2 * math.sin(a), fill=_blend(0, 180, 255, 0.55 * glow), width=2)
