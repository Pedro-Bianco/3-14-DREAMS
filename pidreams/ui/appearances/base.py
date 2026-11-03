"""What every center-panel appearance does the same way.

Animation loop, pausing while the window is minimized, switching to the fallback when
drawing breaks, and the smoothed voice volume. The subclass only draws one frame in `_frame()`.
"""

import logging
import tkinter as tk

log = logging.getLogger(__name__)

STATES = ("idle", "listening", "thinking", "speaking")

# Measured on the pt_BR-faber voice (93 ms blocks): median RMS 0.124, p90 0.224.
# With 4.2, average speech sits mid-scale and only the peaks reach the top.
_VOICE_GAIN = 4.2
_VOICE_FLOOR = 0.008
_ERRORS_BEFORE_SWAP = 3
_MINIMIZED_WAIT_MS = 250


def _voice_level() -> float:
    try:
        from pidreams.audio.tts import VOICE_LEVEL
        return VOICE_LEVEL[0]
    except Exception:
        return 0.0


class Appearance(tk.Canvas):
    # 25 fps: with painting on screen, at 30 fps the face and the brain went over 15% of a
    # core; at 25 all of them stay below it and still above 20 fps.
    INTERVAL_MS = 40
    # Largest size in screen pixels whose drawing stays within 15% of a core; each
    # appearance sets its own from tests/eval/appearance_cost.py. Not scaled by px(): the
    # cost depends on the real pixel count, whatever the Windows scale.
    MAX_SIZE = 300

    def __init__(self, parent, width: int, height: int, bg: str, on_fail=None):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0)
        self.state = "idle"
        self.voice = 0.0                # speech volume from 0 to 1, smoothed
        self._t = 0.0
        self._errors = 0
        self._on_fail = on_fail
        self._running = True
        self.after(1, self._loop)     # after the subclass's __init__

    def set_state(self, state: str):
        self.state = state if state in STATES else "idle"

    def stop(self):
        self._running = False

    def _frame_holder(self):
        raise NotImplementedError

    def _loop(self):
        if not self._running:
            return
        try:
            minimized = self.winfo_toplevel().state() == "iconic"
        except tk.TclError:           # widget destroyed between two frames
            return
        if minimized:                # no CPU spent on what nobody sees
            self.after(_MINIMIZED_WAIT_MS, self._loop)
            return
        self._t += self.INTERVAL_MS / 1000
        target = min(1.0, max(0.0, (_voice_level() - _VOICE_FLOOR) * _VOICE_GAIN))
        # Rises fast and falls a bit slower: follows the syllables without jitter.
        self.voice += (target - self.voice) * (0.65 if target > self.voice else 0.35)
        try:
            self._frame_holder()
            self._errors = 0
        except Exception as e:        # never bring the panel down because of the animation
            self._errors += 1
            log.warning(f"[Appearance] frame error in {type(self).__name__}: {e!r}")
            if self._errors == _ERRORS_BEFORE_SWAP and self._on_fail:
                self._on_fail()
        self.after(self.INTERVAL_MS, self._loop)
