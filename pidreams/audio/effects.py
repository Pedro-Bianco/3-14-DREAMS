"""'Assistant' voice effect: more presence, a slight metallic shimmer and a short room echo — the sound
of a sci-fi AI talking through the room. Applied to any voice, chunk by chunk, so a streaming voice
still starts at once.

The three strengths are the ones the maintainer compared by ear on 2026-11-04 ("forte" chosen).
"""

import numpy as np

STRENGTHS = {"leve": 0.6, "medio": 1.0, "forte": 1.6}
_ECHOES_MS = ((37, 0.18), (53, 0.12), (71, 0.08))


class AssistantEffect:
    """process() each chunk in order, then flush() once for the tail of the echoes. Keeps what the
    delays need from the previous chunks, so the result does not depend on where chunks are cut."""

    def __init__(self, rate: int, strength: str):
        self.k = STRENGTHS.get(strength)
        self.rate = rate
        self._prev = 0.0                                      # last input sample (presence filter)
        self._n = 0                                           # samples processed (shimmer phase)
        self._y = np.zeros(int(0.0031 * rate) + 2, np.float32)               # shimmer looks back ≤3 ms
        self._echoes = [(int(rate * ms / 1000), gain) for ms, gain in _ECHOES_MS]
        self._c = np.zeros(self._echoes[-1][0], np.float32)                  # echoes look back ≤71 ms

    def process(self, audio: np.ndarray) -> np.ndarray:
        if self.k is None or not len(audio):
            return audio
        k, x = self.k, np.asarray(audio, dtype=np.float32)
        y = x + 0.35 * k * np.diff(x, prepend=np.float32(self._prev))     # presence: a bit of the high end
        ext_y = np.concatenate([self._y, y])
        n = self._n + np.arange(len(y))
        delay = (0.002 + 0.001 * np.sin(2 * np.pi * 0.6 * n / self.rate)) * self.rate   # moving 1-3 ms copy
        c = (1 - 0.15 * k) * y + 0.25 * k * ext_y[(len(self._y) + np.arange(len(y)) - delay).astype(np.int64)]
        out = self._mix_echoes(c)
        self._prev, self._n = float(x[-1]), self._n + len(x)
        self._y = ext_y[-len(self._y):]
        return out

    def flush(self) -> np.ndarray:
        """The echoes still ringing after the last chunk."""
        if self.k is None:
            return np.zeros(0, np.float32)
        return self._mix_echoes(np.zeros(len(self._c), np.float32), dry=False)

    def _mix_echoes(self, c: np.ndarray, dry: bool = True) -> np.ndarray:
        ext_c = np.concatenate([self._c, c])
        start = len(self._c)
        out = c.copy() if dry else np.zeros(len(c), np.float32)
        for d, gain in self._echoes:
            out += gain * self.k * ext_c[start - d:start - d + len(c)]
        self._c = ext_c[-len(self._c):]
        # No gain: on a Pocket TTS sentence (2026-11-04) the mix kept 86-90% of the dry loudness with
        # peaks under 0.95; the clip only guards against a louder voice.
        return np.clip(out, -1.0, 1.0).astype(np.float32)


def assistant(audio: np.ndarray, rate: int, strength: str) -> np.ndarray:
    """The whole sentence with the effect (the echo tail included); unchanged when off."""
    shaper = AssistantEffect(rate, strength)
    if shaper.k is None or not len(audio):
        return audio
    return np.concatenate([shaper.process(audio), shaper.flush()])
