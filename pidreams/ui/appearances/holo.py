"""What the 3D hologram appearances (face, brain) share: an opaque 8-bit image painted with numpy,
the dots with a soft halo, and the turn towards the mouse pointer.

One opaque image per frame is far cheaper than thousands of Canvas items (measured on the
monitor's globe: 7.4 ms against 218 ms for 10 000 points), and painting in 8 bits avoids the
full-frame float work that took most of the face's first version (560 px: 22% → 14% of a core).
"""

import math

import numpy as np
from PIL import Image, ImageTk

from pidreams.ui import theme
from pidreams.ui.appearances.base import Appearance


def rgb(hex_color: str) -> np.ndarray:
    return np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


class HoloAppearance(Appearance):
    MAX_YAW, MAX_PITCH = 0.55, 0.35     # radians the object turns at most towards the cursor
    YAW_OFFSET = PITCH_OFFSET = 0.0     # resting angle (the brain rests in three-quarter view)
    FOLLOW = 0.18                       # share of the way to the cursor's direction per frame

    def __init__(self, parent, size: int, bg: str, on_fail=None):
        super().__init__(parent, width=size, height=size, bg=bg, on_fail=on_fail)
        self.size = size
        self._bg = rgb(bg)
        self._blank = np.empty((size, size, 3), np.uint8)
        self._blank[:] = self._bg.astype(np.uint8)
        self._photo = ImageTk.PhotoImage(Image.new("RGB", (size, size), bg))
        self.create_image(0, 0, anchor="nw", image=self._photo)
        self._yaw = self._pitch = 0.0
        self._gaze = np.zeros(2, np.float32)       # where the object "looks", -1..1 on each axis

    # ── cursor ──

    def _follow_cursor(self) -> None:
        """Turns towards the mouse pointer, smoothly; still when the pointer is still."""
        try:
            px, py = self.winfo_pointerxy()
            dx = px - (self.winfo_rootx() + self.size / 2)
            dy = py - (self.winfo_rooty() + self.size / 2)
        except Exception:
            return
        reach = self.size * 1.6
        yaw = max(-self.MAX_YAW, min(self.MAX_YAW, math.atan2(dx, reach)))
        pitch = max(-self.MAX_PITCH, min(self.MAX_PITCH, math.atan2(dy, reach)))
        self._yaw += (yaw - self._yaw) * self.FOLLOW
        self._pitch += (pitch - self._pitch) * self.FOLLOW
        gaze = np.array([dx, dy], np.float32) / max(math.hypot(dx, dy), reach * 0.5)
        self._gaze += (gaze - self._gaze) * 0.35

    def _rotation(self) -> np.ndarray:
        yaw, pitch = self._yaw + self.YAW_OFFSET, self._pitch + self.PITCH_OFFSET
        cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        r_yaw = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
        r_pitch = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
        return r_pitch @ r_yaw

    # ── painting ──

    def _new_frame(self) -> np.ndarray:
        return self._blank.copy()

    def _show(self, img: np.ndarray) -> None:
        self._photo.paste(Image.fromarray(img))

    def _plot(self, img, x, y, color, strength, halo=False):
        s = img.shape[0]
        x, y = np.asarray(x).astype(np.int32), np.asarray(y).astype(np.int32)
        ok = (x > 0) & (x < s - 1) & (y > 0) & (y < s - 1)
        x, y = x[ok], y[ok]
        c = color[None, :] * np.asarray(strength)[ok][:, None] if np.ndim(strength) else color[None, :] * strength
        # Colors clipped to 0-255 before going into the 8-bit frame (above 255 they would wrap).
        if halo:
            soft = np.clip(self._bg + c * 0.45, 0, 255).astype(np.uint8)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                img[y + dy, x + dx] = np.maximum(img[y + dy, x + dx], soft)
        img[y, x] = np.maximum(img[y, x], np.clip(self._bg + c, 0, 255).astype(np.uint8))

    def _state_colors(self) -> tuple[np.ndarray, np.ndarray]:
        """(base color, accent of the current state)."""
        return rgb(theme.CYAN), rgb(theme.STATE_COLORS.get(self.state, theme.CYAN))
