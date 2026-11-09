"""Which speech recognition runs on each PC, and the fallback when the GPU one cannot load."""

from types import SimpleNamespace

import numpy as np
import pytest

from pidreams.core.settings import Settings
from pidreams.stt import transcriber


@pytest.fixture
def setup(tmp_path, monkeypatch):
    s = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(transcriber, "SETTINGS", s)
    state = {"gpu": "Intel(R) Arc(TM) B580 Graphics", "present": True}
    monkeypatch.setattr("pidreams.hardware.detect.current_profile", lambda: SimpleNamespace(gpu_name=state["gpu"]))
    monkeypatch.setattr(transcriber.openvino_whisper, "present", lambda: state["present"])
    return s, state


def test_auto_picks_the_gpu_model_on_intel_only(setup):
    s, state = setup
    assert transcriber.wanted_engine() == "turbo"
    for gpu in ("NVIDIA GeForce RTX 4070", "AMD Radeon RX 7800 XT", None):
        state["gpu"] = gpu
        assert transcriber.wanted_engine() == "small", gpu


def test_choice_in_the_settings_and_missing_model(setup):
    s, state = setup
    s.set("stt.engine", "small")
    assert transcriber.wanted_engine() == "small"
    s.set("stt.engine", "turbo")
    state["gpu"] = "AMD Radeon RX 7800 XT"
    assert transcriber.wanted_engine() == "turbo"             # chosen by the person
    state["present"] = False
    assert transcriber.wanted_engine() == "small"             # not downloaded yet: keeps working


def test_gpu_that_fails_falls_back_to_the_cpu_with_a_notice(setup, monkeypatch):
    def broken():
        raise RuntimeError("GPU driver too old")

    monkeypatch.setattr(transcriber.openvino_whisper, "OpenVinoWhisper", broken)
    monkeypatch.setattr(transcriber.Transcriber, "_load_small", lambda self: setattr(self, "engine", "small"))
    t = transcriber.Transcriber()
    assert t.engine == "small" and "processador" in t.notice


def test_silence_never_reaches_the_gpu_model(setup, monkeypatch):
    """Over silence the turbo wrote "E aí" (2026-11-09): only voiced audio goes to it."""
    calls = []

    class Fake:
        def transcribe(self, speech):
            calls.append(len(speech))
            return "texto"

    monkeypatch.setattr(transcriber.openvino_whisper, "OpenVinoWhisper", Fake)
    t = transcriber.Transcriber()
    assert t.engine == "turbo"
    silence = (np.random.default_rng(0).standard_normal(16000 * 2) * 0.001).astype(np.float32)
    assert t.transcribe(silence) == "" and calls == []
