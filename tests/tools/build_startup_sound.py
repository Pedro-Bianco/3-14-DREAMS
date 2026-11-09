"""Builds pidreams/assets/sounds/startup.wav, the sound played when the window opens.

Synthesized from scratch (no third-party samples): a soft G major chord that swells slowly, granular
sparkles on both sides and four spaced glass bells (FM synthesis), with a room reverb. Chosen by the
maintainer among 17 candidates on 2026-11-09 ("Aurora"). The shipped file came from a batch of five
candidates generated together, so running this again places the random sparkles slightly differently.

    python -m tests.tools.build_startup_sound
"""

import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

RATE = 44100
OUT = Path(__file__).resolve().parents[2] / "pidreams" / "assets" / "sounds" / "startup.wav"
rng = np.random.default_rng(21)


def n(s):
    return int(RATE * s)


def tt(s):
    return np.arange(n(s)) / RATE


def adsr(length_s, a=0.01, r=0.5):
    x = np.ones(n(length_s))
    ka, kr = max(1, n(a)), max(1, n(r))
    x[:ka] = np.linspace(0, 1, ka)
    x[-kr:] *= np.exp(-np.linspace(0, 5, kr))
    return x


def fm_bell(freq, s, ratio=3.5, index=2.5, decay=2.0):
    t = tt(s)
    mod = index * np.exp(-t * decay * 1.5) * np.sin(2 * np.pi * freq * ratio * t)
    return np.sin(2 * np.pi * freq * t + mod) * np.exp(-t * decay)


def pad(freqs, s, a, r, cutoff):
    t = tt(s)
    x = sum(sum(2 * ((t * f * (1 + d) + rng.uniform()) % 1) - 1 for d in (-0.006, 0, 0.006)) for f in freqs)
    x = sosfilt(butter(2, cutoff, "low", fs=RATE, output="sos"), x / (3 * len(freqs)))
    return x * adsr(s, a, r)


def sparkle(s, count, lo, hi):
    out = np.zeros(n(s))
    for _ in range(count):
        at, f = rng.uniform(0, s - 0.1), rng.uniform(lo, hi)
        grain = np.sin(2 * np.pi * f * tt(0.08)) * np.hanning(n(0.08)) * rng.uniform(0.2, 1)
        out[n(at):n(at) + len(grain)] += grain
    return out


class Mix:
    def __init__(self, s):
        self.l, self.r = np.zeros(n(s)), np.zeros(n(s))

    def add(self, x, at, gain=1.0, pan=0.0):
        i = n(at)
        end = min(len(self.l), i + len(x))
        self.l[i:end] += gain * (1 - max(0, pan)) * x[:end - i]
        self.r[i:end] += gain * (1 + min(0, pan)) * x[:end - i]

    def echo(self, x, at, gain, delay, repeats, fb=0.45):
        for k in range(repeats):
            self.add(x, at + k * delay, gain * fb ** k, pan=-0.7 if k % 2 else 0.7)

    def save(self, path: Path):
        ir_n = n(2.2)
        t = np.arange(ir_n) / RATE
        channels = []
        for ch, seed in ((self.l, 3), (self.r, 4)):
            ir = np.random.default_rng(seed).standard_normal(ir_n) * np.exp(-t * 2.6)
            ir = sosfilt(butter(2, 7000, "low", fs=RATE, output="sos"), ir)
            wet = np.convolve(ch, ir)[:len(ch)]
            channels.append(ch + 0.25 * wet / (np.max(np.abs(wet)) + 1e-9) * np.max(np.abs(ch)))
        x = np.stack(channels, axis=1)
        x = np.tanh(1.3 * x / np.max(np.abs(x)))
        x = x / np.max(np.abs(x)) * 0.89
        fade = n(0.2)
        x[-fade:] *= np.linspace(1, 0, fade)[:, None]
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((x * 32767).astype(np.int16).tobytes())


def main():
    m = Mix(5.0)
    m.add(pad((196.0, 293.66, 392.0, 493.88, 587.33), 4.8, a=1.6, r=2.2, cutoff=3000), 0.0, 0.5)   # G major
    m.add(sparkle(4.0, 70, 2500, 7000), 0.6, 0.08, pan=-0.4)
    m.add(sparkle(4.0, 70, 2500, 7000), 0.7, 0.08, pan=0.4)
    for i, (at, freq) in enumerate(((1.2, 783.99), (1.8, 1174.66), (2.4, 987.77), (3.0, 1567.98))):
        m.add(fm_bell(freq, 2.0, ratio=3.0, index=1.0, decay=1.5), at, 0.12, pan=-0.5 if i % 2 else 0.5)
    m.save(OUT)
    print(OUT, f"{OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
