"""PI dreams face in the center panel: a 3D holographic face of points and lines.

The geometry is MediaPipe's canonical face model (468 points, Apache-2.0; converted by
tests/tools/build_face_mesh.py into assets/face_mesh.json). Each frame turns the head a little,
moves the jaw with the REAL volume of the voice being played (base.Appearance.voice), blinks,
and paints everything with numpy into one opaque image, like the monitor's globe (one image is
far cheaper than thousands of Canvas items).
"""

import json
import math
from pathlib import Path

import numpy as np

from pidreams.ui import theme
from pidreams.ui.appearances.holo import HoloAppearance

MESH_PATH = Path(__file__).resolve().parent.parent / "assets" / "face_mesh.json"

# Eyelids of the canonical model, upper and lower in matching order (MediaPipe landmark ids).
_LIDS = [([246, 161, 160, 159, 158, 157, 173], [7, 163, 144, 145, 153, 154, 155]),
         ([466, 388, 387, 386, 385, 384, 398], [249, 390, 373, 374, 380, 381, 382])]
_UPPER_LIP_INNER, _LOWER_LIP_INNER, _CHIN = 13, 14, 152
_MOUTH_CORNERS = (61, 291)
_MAX_OPENING = 0.075          # of the face height, with the mouth fully open
_EDGE_STEP = 0.011
_SKIN_PER_TRIANGLE = 4        # dots inside each triangle
_IRIS = 0.022                 # iris radius (face height = 1)            # distance between the dots that draw each line (face height = 1)


def _load():
    data = json.loads(MESH_PATH.read_text(encoding="utf-8"))
    v = np.asarray(data["vertices"], dtype=np.float32)
    v -= (v.max(0) + v.min(0)) / 2
    v /= v[:, 1].max() - v[:, 1].min()               # face height = 1, y up, z towards the viewer
    edges = np.asarray(data["edges"], dtype=np.int32)
    return v, edges, np.asarray(data.get("triangles", []), dtype=np.int32).reshape(-1, 3)


class FaceCanvas(HoloAppearance):
    MAX_SIZE = 560      # measured with tests/eval/appearance_cost.py (2026-11-03)

    def __init__(self, parent, size: int = 300, bg: str = theme.GLASS, on_fail=None):
        super().__init__(parent, size, bg, on_fail)
        self._base, self._edges, triangles = _load()
        # "Skin": faint dots inside each triangle (fixed barycentric weights), for volume.
        rng = np.random.default_rng(314)
        w = rng.random((len(triangles) * _SKIN_PER_TRIANGLE, 2)).astype(np.float32)
        flip = w.sum(1) > 1
        w[flip] = 1 - w[flip]
        self._skin_tri = np.repeat(triangles, _SKIN_PER_TRIANGLE, axis=0)
        self._skin_w = np.column_stack([1 - w.sum(1), w[:, 0], w[:, 1]])
        mid = (self._base[_UPPER_LIP_INNER, 1] + self._base[_LOWER_LIP_INNER, 1]) / 2
        chin = self._base[_CHIN, 1]
        y, x = self._base[:, 1], self._base[:, 0]
        # Mouth: the jaw turns (the chin drops more and goes back a little), the lips part more in
        # the middle than at the corners, the upper lip lifts a bit and the corners round or spread.
        # Dropping the whole lower face as one block looked like a puppet.
        half = abs(self._base[_MOUTH_CORNERS[1], 0] - self._base[_MOUTH_CORNERS[0], 0]) / 2
        below = (y < mid).astype(np.float32)
        cheek = np.clip(1 - (np.abs(x) / 0.36) ** 2, 0, 1)
        down = np.clip((mid - y) / max(mid - chin, 1e-6), 0, 1)
        across = np.clip(1 - (x / half) ** 2, 0, 1)
        self._jaw = below * cheek * (0.55 + 0.45 * down)
        self._jaw_back = below * cheek * down
        self._lower_lip = below * (y > mid - 0.07) * across
        self._upper_lip = (y >= mid) * (y < mid + 0.05) * across
        self._lips = np.clip(1 - ((y - mid) / 0.07) ** 2, 0, 1) * (np.abs(x) < half * 1.3)
        self._round = 0.5            # 0 = spread ("e"), 1 = rounded ("o"); changes on each syllable
        self._last_voice = 0.0
        # Dots along each edge, as (edge index, fraction): the lines follow the mesh as it moves.
        a, b = self._base[self._edges[:, 0]], self._base[self._edges[:, 1]]
        counts = np.maximum(1, (np.linalg.norm(a - b, axis=1) / _EDGE_STEP).astype(int))
        self._dot_edge = np.repeat(np.arange(len(self._edges)), counts)
        self._dot_t = np.concatenate([np.arange(1, n + 1) / (n + 1) for n in counts]).astype(np.float32)[:, None]
        self._eyes = np.array([i for upper, lower in _LIDS for i in upper + lower])
        self._mouth = np.where((np.abs(y - mid) < 0.05) & (np.abs(x) < 0.17))[0]
        self._next_blink = 2.0

    # ── geometry of this frame ──

    def _shape(self) -> np.ndarray:
        v = self._base.copy()
        if self.state == "speaking" and self.voice > 0.02:
            if self.voice > self._last_voice + 0.12 and self.voice > 0.3:       # a new syllable
                self._round = (math.sin(self._t * 12.9898) * 43758.5453) % 1.0
            opening = _MAX_OPENING * self.voice ** 0.8
            v[:, 1] -= opening * (self._jaw + 0.45 * self._lower_lip)
            v[:, 1] += opening * 0.18 * self._upper_lip
            v[:, 2] -= opening * 0.5 * self._jaw_back
            v[:, 0] *= 1 + self.voice * (0.10 * (1 - self._round) - 0.18 * self._round) * self._lips
        self._last_voice = self.voice
        blink = self._blink()
        if blink:
            for upper, lower in _LIDS:
                v[upper, 1] -= (v[upper, 1] - v[lower, 1]) * blink
        return v

    def _blink(self) -> float:
        """0 → open, 1 → closed; a blink every 3 to 6 s, ~0.2 s long."""
        if self._t > self._next_blink + 0.2:
            self._next_blink = self._t + 3 + 3 * abs(math.sin(self._t * 1.7))
        phase = self._t - self._next_blink
        return math.sin(phase / 0.2 * math.pi) if 0 <= phase <= 0.2 else 0.0

    # ── drawing ──

    def _frame_holder(self):
        s = self.size
        self._follow_cursor()
        v = self._shape() @ self._rotation().T
        scale = s * 0.78
        sx, sy = s / 2 + v[:, 0] * scale, s / 2 - v[:, 1] * scale + s * 0.02
        depth = (v[:, 2] - v[:, 2].min()) / max(float(np.ptp(v[:, 2])), 1e-6)    # 0 back → 1 front
        base, accent = self._state_colors()
        glow = 0.85 + 0.3 * self.voice if self.state == "speaking" else 0.85
        img = self._new_frame()

        # Lines: dots interpolated between the two ends of each edge.
        e = self._edges[self._dot_edge]
        t = self._dot_t[:, 0]
        lx = sx[e[:, 0]] + (sx[e[:, 1]] - sx[e[:, 0]]) * t
        ly = sy[e[:, 0]] + (sy[e[:, 1]] - sy[e[:, 0]]) * t
        ld = depth[e[:, 0]] + (depth[e[:, 1]] - depth[e[:, 0]]) * t
        if self.state == "thinking":                     # a band of light sweeping the face
            band = np.exp(-((ly / s - (0.5 + 0.42 * math.sin(self._t * 1.6))) ** 2) / 0.003)
        else:
            band = 0.0
        self._plot(img, lx, ly, base, (0.32 + 0.43 * ld) * glow)
        if self.state == "thinking":
            self._plot(img, lx, ly, accent, 1.1 * band)
        # Skin: dots inside the triangles, faint, brighter in front.
        if len(self._skin_tri):
            k = self._skin_tri
            wx = (sx[k] * self._skin_w).sum(1)
            wy = (sy[k] * self._skin_w).sum(1)
            wd = (depth[k] * self._skin_w).sum(1)
            self._plot(img, wx, wy, base, (0.08 + 0.22 * wd) * glow)
        # Irises: a ring and a bright centre in the middle of each eye (closed while blinking).
        if self._blink() < 0.6:
            ring = np.linspace(0, 2 * np.pi, 18, endpoint=False)
            for upper, lower in _LIDS:
                cx, cy = sx[upper + lower].mean(), sy[upper + lower].mean()
                reach_x = (sx[upper + lower].max() - sx[upper + lower].min()) * 0.22
                reach_y = (sy[lower].mean() - sy[upper].mean()) * 0.3
                cx, cy = cx + self._gaze[0] * reach_x, cy + self._gaze[1] * reach_y
                r = _IRIS * scale
                self._plot(img, cx + r * np.cos(ring), cy + r * np.sin(ring) * 0.85, accent, np.full(18, 0.9), halo=True)
                self._plot(img, np.array([cx]), np.array([cy]), accent, np.array([1.2]), halo=True)
        # Points: every vertex, brighter in front; eyes and mouth in the state's color.
        self._plot(img, sx, sy, base, (0.6 + 0.5 * depth) * glow, halo=True)
        hi = np.concatenate([self._eyes, self._mouth])
        self._plot(img, sx[hi], sy[hi], accent, np.full(len(hi), 1.0), halo=True)

        self._show(img)
