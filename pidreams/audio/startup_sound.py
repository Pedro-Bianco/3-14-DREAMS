"""The sound played when the window opens, with the startup animation (ui/boot_splash.py).

Original, synthesized by tests/tools/build_startup_sound.py ("Aurora", chosen on 2026-11-09).
Played in the background on the output device and volume of the settings; any audio problem only
goes to the log (a missing chime must never stop the app from opening).
"""

import logging
import threading
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SOUND = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "startup.wav"
# The file is mastered loud (rms -13.6 dBFS) and played ~11 dB above the default voice (-24.3 dBFS
# while speaking); -9 dB keeps it just above the voice (measured 2026-11-11, user found it too loud).
GAIN = 0.35


def _read() -> tuple[np.ndarray, int]:
    with wave.open(str(SOUND), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return data.reshape(-1, channels), rate


def play(device: int | None, volume: float) -> None:
    def run():
        try:
            import sounddevice as sd

            data, rate = _read()
            sd.play(data * GAIN * max(0.0, min(1.0, volume)), rate, device=device)
        except Exception as e:                 # noqa: BLE001 — no device, file missing: log only
            log.warning("startup sound not played: %r", e)

    threading.Thread(target=run, daemon=True, name="startup-sound").start()
