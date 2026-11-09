"""Startup animation in the center of the window while the app loads (~30 s on the reference PC).

HUD rings turning around a progress ring that follows the real steps, with the step's name and one
dot per step. Each step's share of the ring comes from its measured time (2026-11-09, Arc B580):
memory 8 s, speech recognition 4 s, voice 4 s, conversation model 14 s, microphone 1.5 s. Inside a
step the ring creeps toward the step's end by its expected time and never passes it, so a slow PC
does not show 100% early; a fast step just jumps ahead. When everything is ready a pulse expands
and the appearance takes the place.
"""

import math
import time
import tkinter as tk
from typing import Callable

from pidreams.ui import theme

# (event name, label shown, expected seconds)
STEPS = (
    ("memoria", "Memória e documentos", 8.0),
    ("reconhecimento", "Reconhecimento de voz", 4.0),
    ("voz", "Voz", 4.0),
    ("modelo", "Modelo de conversa", 14.0),
    ("microfone", "Microfone", 1.5),
)
_TOTAL = sum(s[2] for s in STEPS)
_FRAME_MS = 33                   # ~30 fps: smooth enough for rings, cheap on the CPU
_FINISH_S = 0.7
_CENTER_Y = 0.43                 # rings a bit above the middle: the step's name and dots go below
_OUTER, _PROGRESS, _INNER = 0.37, 0.31, 0.23     # radii, as a share of the size


def _mix(color: str, toward: str, amount: float) -> str:
    """color moved toward another by amount (0..1): Tk has no alpha, so fades are color blends."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(toward[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


class BootSplash(tk.Canvas):
    """step(name) when a step starts; ready(on_done) when everything is loaded."""

    def __init__(self, parent, size: int, bg: str):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self._size, self._bg = size, bg
        self._index = 0
        self._step_started = time.monotonic()
        self._shown = 0.0                         # progress drawn (0..1), eased toward the target
        self._done_at: float | None = None
        self._on_done: Callable[[], None] | None = None
        self._t0 = time.monotonic()
        self._running = True
        self.after(1, self._tick)

    # ── what the app tells it ────────────────────────────────────────────────

    def step(self, name: str) -> None:
        names = [s[0] for s in STEPS]
        if name in names and names.index(name) >= self._index:
            self._index = names.index(name)
            self._step_started = time.monotonic()

    def ready(self, on_done: Callable[[], None]) -> None:
        if self._done_at is None:
            self._index = len(STEPS)
            self._done_at = time.monotonic()
            self._on_done = on_done

    def stop(self) -> None:
        self._running = False

    def resize(self, size: int) -> None:
        self._size = size
        self.configure(width=size, height=size)

    # ── progress ─────────────────────────────────────────────────────────────

    def _target(self) -> float:
        if self._index >= len(STEPS):
            return 1.0
        before = sum(s[2] for s in STEPS[:self._index])
        expected = STEPS[self._index][2]
        inside = min(0.92, (time.monotonic() - self._step_started) / expected)   # never claims the step done
        return (before + inside * expected) / _TOTAL

    # ── drawing ──────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self._running:
            return
        try:
            hidden = self.winfo_toplevel().state() in ("iconic", "withdrawn")
        except tk.TclError:
            return
        if not hidden:
            self._shown += (self._target() - self._shown) * (0.25 if self._done_at else 0.08)
            self._draw()
        if self._done_at is not None and time.monotonic() - self._done_at > _FINISH_S:
            self._running = False
            if self._on_done:
                self._on_done()
            return
        self.after(_FRAME_MS, self._tick)

    def _ring(self, radius: float, start: float, extent: float, width: float, color: str, style=tk.ARC):
        cx, cy = self._size / 2, self._size * _CENTER_Y
        self.create_arc(cx - radius, cy - radius, cx + radius, cy + radius, start=start, extent=extent,
                        style=style, outline=color, width=width)

    def _draw(self) -> None:
        self.delete("all")
        s, c, cy = self._size, self._size / 2, self._size * _CENTER_Y
        now = time.monotonic() - self._t0
        finish = 0.0 if self._done_at is None else min(1.0, (time.monotonic() - self._done_at) / _FINISH_S)
        fade = finish                                   # everything but the pulse fades out at the end

        cyan, violet = _mix(theme.CYAN, self._bg, fade), _mix(theme.VIOLET, self._bg, fade)
        dim = _mix(theme.CYAN, self._bg, 0.75 + 0.25 * fade)

        # Outer dashed ring turning slowly; inner violet ticks turning the other way.
        for k in range(24):
            self._ring(s * _OUTER, (k * 15 + now * 20) % 360, 9, max(1, s * 0.008), dim)
        for k in range(12):
            self._ring(s * _INNER, (k * 30 - now * 45) % 360, 12, max(1, s * 0.006), _mix(violet, self._bg, 0.4))

        # Progress ring: dark track, glow and the arc itself, from the top clockwise.
        width = max(3, s * 0.03)
        self._ring(s * _PROGRESS, 90, -359.9, width, _mix(theme.CYAN, self._bg, 0.88))
        extent = -360 * max(0.002, min(1.0, self._shown))
        self._ring(s * _PROGRESS, 90, extent, width * 2.2, _mix(cyan, self._bg, 0.75))
        self._ring(s * _PROGRESS, 90, extent, width, cyan)
        # A bright head at the tip of the arc.
        angle = math.radians(90 + extent)
        hx, hy = c + s * _PROGRESS * math.cos(angle), cy - s * _PROGRESS * math.sin(angle)
        r = width * 0.9
        self.create_oval(hx - r, hy - r, hx + r, hy + r, fill=_mix(theme.SPARK, self._bg, fade), outline="")

        # Center: name and percentage.
        text = _mix(theme.TEXT, self._bg, fade)
        self.create_text(c, cy - s * 0.04, text="PI", fill=text, font=(theme.TECH_FAMILY, max(10, int(s * 0.11)), "bold"))
        self.create_text(c, cy + s * 0.045, text="dreams", fill=violet, font=(theme.TECH_FAMILY, max(8, int(s * 0.045))))
        self.create_text(c, cy + s * 0.11, text="100%" if self._done_at else f"{round(100 * self._shown)}%", fill=cyan,
                         font=(theme.TECH_FAMILY, max(8, int(s * 0.045))))

        # Below the rings: current step and one dot per step.
        label = "Pronto" if self._index >= len(STEPS) else STEPS[self._index][1] + "…"
        self.create_text(c, s * 0.93, text=label, fill=_mix(theme.MUTED, self._bg, fade),
                         font=(theme.TECH_FAMILY, max(8, int(s * 0.04))))
        gap, dot = s * 0.05, max(2, s * 0.011)
        x0 = c - gap * (len(STEPS) - 1) / 2
        for i in range(len(STEPS)):
            color = cyan if i < self._index else (violet if i == self._index else dim)
            x = x0 + i * gap
            self.create_oval(x - dot, s * 0.86 - dot, x + dot, s * 0.86 + dot, fill=color, outline="")

        # The finishing pulse: a ring that grows past the others and fades.
        if finish:
            radius = s * (_PROGRESS + 0.12 * finish)
            self._ring(radius, 90, -359.9, max(1, width * (1 - finish) * 2), _mix(theme.SPARK, self._bg, finish))
