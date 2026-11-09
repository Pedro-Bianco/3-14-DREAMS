"""Two-clap detector on synthetic signals (no microphone)."""

import numpy as np

from pidreams.audio.claps import FRAME, SAMPLE_RATE, ClapDetector, calibrated_level

rng = np.random.default_rng(7)


def _room(seconds: float, level: float = 0.003) -> np.ndarray:
    return (rng.standard_normal(int(seconds * SAMPLE_RATE)) * level).astype(np.float32)


def _clap(gain: float = 0.8) -> np.ndarray:
    """A snap: noise burst decaying in ~15 ms (gain 0.8 peaks ~0.35 RMS in its first frame,
    like the measured claps)."""
    n = int(0.03 * SAMPLE_RATE)
    return (rng.standard_normal(n) * gain * np.exp(-np.arange(n) / (0.004 * SAMPLE_RATE))).astype(np.float32)


def _with_claps(times: list[float], total: float = 3.0, gain: float = 0.8, room: float = 0.003) -> np.ndarray:
    signal = _room(total, room)
    for t in times:
        start = int(t * SAMPLE_RATE)
        burst = _clap(gain)
        signal[start:start + len(burst)] += burst
    return signal


def _detections(signal: np.ndarray, min_level: float = 0.2) -> int:
    detector = ClapDetector(min_level)
    return sum(detector.feed(signal[i:i + FRAME]) for i in range(0, len(signal) - FRAME + 1, FRAME))


def test_two_claps_wake():
    assert _detections(_with_claps([1.2, 1.55])) == 1


def test_two_desk_knocks_do_not_wake():
    """Everyday snaps measured at 0.03-0.10 woke the app with the first floor (2026-11-08)."""
    assert _detections(_with_claps([1.2, 1.4], gain=0.2)) == 0


def test_quick_weak_pair_does_not_wake():
    """The false wake seen in the app: 0.16/0.19, 160 ms apart (2026-11-08)."""
    assert _detections(_with_claps([1.2, 1.36], gain=0.4)) == 0
    assert _detections(_with_claps([1.2, 1.36])) == 0          # even loud, too quick for two claps


def test_one_clap_does_not_wake():
    assert _detections(_with_claps([1.2])) == 0


def test_claps_too_far_apart_do_not_wake():
    assert _detections(_with_claps([1.0, 2.2])) == 0


def test_three_snaps_are_knocking_not_a_call():
    assert _detections(_with_claps([1.0, 1.3, 1.6])) == 0


def test_steady_typing_does_not_wake():
    assert _detections(_with_claps([0.6 + 0.18 * i for i in range(12)], total=4.0)) == 0


def test_speech_like_sound_does_not_wake():
    """Held, loud sound with syllable-like bursts of 150-300 ms."""
    signal = _room(4.0)
    t = np.arange(len(signal)) / SAMPLE_RATE
    for start, length in [(0.8, 0.25), (1.15, 0.2), (1.5, 0.3), (2.1, 0.15), (2.4, 0.25)]:
        part = (t >= start) & (t < start + length)
        signal[part] += 0.3 * np.sin(2 * np.pi * 180 * t[part])
    assert _detections(signal) == 0


def test_music_does_not_wake():
    t = np.arange(4 * SAMPLE_RATE) / SAMPLE_RATE
    music = 0.2 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 2 * t))
    assert _detections((music + _room(4.0)).astype(np.float32)) == 0


def test_rest_after_a_wake():
    """A second pair right after waking is ignored (1 s pause)."""
    assert _detections(_with_claps([0.8, 1.1, 1.9, 2.2], total=3.0)) == 1


def test_quiet_microphone_is_heard_after_calibrating():
    """A low-gain microphone: claps arrive at a third of the volume. The default floor misses
    them; the floor calibrated from those same claps hears them."""
    quiet = _with_claps([1.2, 1.55], gain=0.25, room=0.001)     # the room is quieter too
    assert _detections(quiet) == 0
    assert _detections(quiet, min_level=calibrated_level([0.11, 0.13, 0.12, 0.10])) == 1


def test_calibrated_level_is_half_the_weakest_clap_within_limits():
    assert calibrated_level([0.29, 0.58, 0.41]) == 0.145
    assert calibrated_level([0.01, 0.02]) == 0.02        # never below the floor
    assert calibrated_level([1.0, 1.0]) == 0.5            # nor above the ceiling
