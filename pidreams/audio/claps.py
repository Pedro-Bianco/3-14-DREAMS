"""Two claps wake the app from the tray.

Signal only, no model: each 10 ms frame becomes one number (its loudness) and the audio is
dropped right away — nothing is recorded, transcribed or kept. A clap is a frame much louder
than the room (the median of the last second) that falls back under half its peak within a
few frames: speech and music hold their sound, a clap is a snap. Two claps 180–700 ms apart,
followed by a short silence (a third snap means typing or knocking, not a call), wake the app.
"""

import collections
import logging
from typing import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME = 160                      # 10 ms

# From the live evaluation (tests/eval/claps.py, 2026-11-08, quiet room at ~0.002): claps peaked
# 0.29-0.60 (84-320x the room) with 210-280 ms between them, 19 of 20 pairs detected. False
# wakes seen: everyday snaps at 0.03-0.10, and one pair at 0.16/0.19, 34-41x the room, 160 ms
# apart. Each limit below rejects that pair on its own and keeps every clap with margin.
RISE = 40.0                      # times louder than the room
# Absolute floor (RMS, full scale = 1.0). It depends on the microphone's gain, so each user can
# replace it by calibrating (Settings > Bandeja): half of their weakest clap.
MIN_LEVEL = 0.20
CALIBRATION_RANGE = (0.02, 0.5)
DECAY_FRAMES = 4                 # must fall under half the peak within 40 ms
GAP_MIN, GAP_MAX = 18, 70        # frames between the two claps (180–700 ms)
QUIET_AFTER = 35                 # frames with no third snap after the pair (350 ms)
REFRACTORY = 100                 # frames ignored after a wake (1 s)
_HISTORY = 100                   # frames in the room estimate (1 s)


class ClapDetector:
    """feed() one frame at a time; True on the frame that confirms two claps."""

    def __init__(self, min_level: float = MIN_LEVEL):
        self._min_level = min_level
        self._levels: collections.deque = collections.deque(maxlen=_HISTORY)
        self._frame = 0
        self._peak = 0.0                 # > 0 while a snap candidate is being followed
        self._peak_start = 0
        self._armed = True               # back near the room level since the last loud frame
        self._claps: list[tuple[int, float]] = []    # (frame, peak) of the recent claps
        self._room = 0.0                 # room level when the last snap started
        self.last = ""                   # numbers of the last wake, for the log (no audio)
        self.last_peaks: tuple[float, float] = (0.0, 0.0)
        self.on_snap = None              # evaluation only: called with (peak, room) of every snap
        self._quiet_until = 0
        self._noisy_until = 0

    def reset(self) -> None:
        on_snap = self.on_snap
        self.__init__(self._min_level)
        self.on_snap = on_snap

    def feed(self, frame: np.ndarray) -> bool:
        self._frame += 1
        level = float(np.sqrt(np.mean(np.square(frame, dtype=np.float32))))
        room = float(np.median(self._levels)) if len(self._levels) >= 10 else level
        self._levels.append(level)
        if self._frame < self._quiet_until:
            return False

        if self._peak:
            self._peak = max(self._peak, level)
            if level < self._peak / 2:
                peak, self._peak = self._peak, 0.0
                self._clap(peak)
            elif self._frame - self._peak_start > DECAY_FRAMES:
                self._peak, self._armed = 0.0, False      # a held sound: not a clap
        elif self._armed and level > max(room * RISE, self._min_level):
            self._peak, self._peak_start, self._room = level, self._frame, room
        elif not self._armed and level < max(room * 2, self._min_level / 2):
            self._armed = True

        if len(self._claps) == 2 and self._frame - self._claps[1][0] > QUIET_AFTER:
            (first, peak1), (second, peak2) = self._claps
            self.last_peaks = (peak1, peak2)
            self.last = f"peaks {peak1:.3f}/{peak2:.3f}, room {self._room:.4f}, gap {(second - first) * 10} ms"
            self._claps.clear()
            self._quiet_until = self._frame + REFRACTORY
            return True
        return False

    def _clap(self, peak: float) -> None:
        if self.on_snap:
            self.on_snap(peak, self._room)
        if self._claps and self._frame - self._claps[-1][0] < GAP_MIN:
            return                                   # the room echoing the same clap
        if self._frame < self._noisy_until or len(self._claps) == 2:
            # A third snap: knocking or typing. Wait for a second without snaps.
            self._claps = []
            self._noisy_until = self._frame + REFRACTORY
        elif self._claps and self._frame - self._claps[-1][0] <= GAP_MAX:
            self._claps.append((self._frame, peak))
        else:
            self._claps = [(self._frame, peak)]


def calibrated_level(peaks: list[float]) -> float:
    """The floor for this microphone: half of the weakest clap heard while calibrating."""
    low, high = CALIBRATION_RANGE
    return round(min(high, max(low, min(peaks) / 2)), 3)


class ClapListener:
    """The microphone, open only while the app sleeps, feeding the detector.

    on_claps runs on the audio thread: it must only hand the event over (a queue), never touch
    Tk. ignore() true (the app's own voice or radio playing) skips the frames, so the app never
    wakes itself."""

    def __init__(self, device: int | None, on_claps: Callable[[], None], ignore: Callable[[], bool],
                 min_level: float = MIN_LEVEL):
        self._device = device
        self._on_claps = on_claps
        self._ignore = ignore
        self._detector = ClapDetector(min_level)
        self._stream: sd.InputStream | None = None

    @property
    def detector(self) -> ClapDetector:
        return self._detector

    @property
    def last(self) -> str:
        return self._detector.last

    @property
    def active(self) -> bool:
        return self._stream is not None and self._stream.active

    def start(self) -> None:
        """Raises when there is no usable microphone (the caller shows it and tries again)."""
        self.stop()
        self._detector.reset()
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                      blocksize=FRAME, device=self._device, callback=self._callback)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log.debug("clap listener close: %r", e)
            self._stream = None

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        if self._ignore():
            self._detector.reset()
            return
        if self._detector.feed(indata[:, 0]):
            log.info("two claps heard (%s)", self._detector.last)
            self._on_claps()
