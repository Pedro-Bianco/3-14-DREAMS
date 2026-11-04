"""Vozes: lista, download (servidor falso), motor de voz com Pocket TTS e Kokoro falsos, efeito de
assistente e o app sem voz quando os arquivos faltam. Sem rede e sem os modelos de verdade."""

import io
import threading

import numpy as np
import pytest

from pidreams.audio import tts, voices
from pidreams.hardware import models


def test_vozes_e_voz_antiga_vira_a_padrao():
    assert voices.choices() == ["pocket-baritono", "kokoro-alex", "kokoro-santa", "kokoro-dora", "kokoro-onyx",
                                "kokoro-alex-santa"]
    assert voices.resolve("kokoro-onyx") == "kokoro-onyx" and voices.is_kokoro("kokoro-onyx")
    assert voices.resolve("voz-de-versao-antiga") == voices.DEFAULT == "pocket-baritono"   # saved by an older version
    assert not voices.is_kokoro("voz-de-versao-antiga")


@pytest.fixture
def kokoro_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(models.paths, "models_dir", lambda kind: tmp_path / kind)
    monkeypatch.setattr(models, "_KOKORO_FILES", {"modelo.onnx": ("https://exemplo.com/modelo.onnx", 5),
                                                "vozes.bin": ("https://exemplo.com/vozes.bin", 3)})
    return tmp_path / "kokoro"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_baixa_os_dois_arquivos_e_reporta_progresso(kokoro_folder, monkeypatch):
    bodies = {"modelo.onnx": b"12345", "vozes.bin": b"abc"}
    asked = []

    def urlopen(request, timeout=30):
        name = request.full_url.rsplit("/", 1)[-1]
        asked.append((name, request.headers.get("User-agent")))
        return _Response(bodies[name])
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    progress = []
    models.download_kokoro(lambda pct, text: progress.append(pct), threading.Event())
    assert models.kokoro_present()
    assert [a[0] for a in asked] == ["modelo.onnx", "vozes.bin"] and asked[0][1].startswith("PI-dreams/")
    assert progress[-1] == 100 and not list(kokoro_folder.glob("*.part"))
    asked.clear()
    models.download_kokoro(lambda *a: None, threading.Event())          # already there: nothing to fetch
    assert asked == []


def test_download_incompleto_nao_deixa_arquivo_pela_metade(kokoro_folder, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=30: _Response(b"12"))
    with pytest.raises(models.DownloadFailed, match="incompleto"):
        models.download_kokoro(lambda *a: None, threading.Event())
    assert not models.kokoro_present() and not list(kokoro_folder.glob("*"))


class _FakeKokoro:
    def __init__(self, model, voices_file):
        self.calls = []

    def get_voice_style(self, name):
        return np.full(4, {"pm_alex": 1.0, "pm_santa": 3.0}[name], dtype=np.float32)

    def create(self, text, voice, lang, speed):
        self.calls.append((text, voice, lang, speed))
        return np.ones(2400, dtype=np.float32), 24000


def test_motor_fala_com_a_voz_kokoro(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=_FakeKokoro))
    monkeypatch.setattr(models, "kokoro_present", lambda: True)
    monkeypatch.setattr(tts.CONFIG.__class__, "voice_length_scale", property(lambda self: 1.25))
    monkeypatch.setattr(tts.SETTINGS, "get", lambda key: "" if key == "voice.effect" else None)
    engine = tts.TTSEngine()
    engine._load_voice("kokoro-alex")
    assert engine._sample_rate == 24000
    chunks = list(engine._synthesize("Boa tarde, senhor."))
    assert len(chunks) == 1 and chunks[0].dtype == np.float32
    assert engine._kokoro.calls == [("Boa tarde, senhor.", "pm_alex", "pt-br", 0.8)]   # speed = 1 / length scale


def test_sem_os_arquivos_o_app_abre_mudo(monkeypatch):
    monkeypatch.setattr(models, "pocket_present", lambda: False)
    monkeypatch.setattr(models, "kokoro_present", lambda: False)
    monkeypatch.setattr(tts.SETTINGS, "subscribe", lambda fn: None)
    monkeypatch.setattr(tts.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    engine = tts.TTSEngine()
    engine.start()                                    # no exception
    assert engine._kokoro is None and engine._pocket is None and list(engine._voice_chunks("oi")) == []


def test_efeito_de_assistente():
    from pidreams.audio import effects
    rate = 24000
    voice = (0.5 * np.sin(2 * np.pi * 220 * np.arange(rate) / rate)).astype(np.float32)
    assert effects.assistant(voice, rate, "") is voice                       # off: untouched
    out = effects.assistant(voice, rate, "forte")
    assert out.dtype == np.float32 and len(out) == rate + int(rate * 71 / 1000)  # room for the last echo
    assert np.max(np.abs(out)) <= 1.0 and not np.allclose(out[:rate], voice)


def test_efeito_em_pedacos_e_igual_ao_da_frase_inteira():
    """A streaming voice hands the effect any chunk sizes: the result must not depend on the cuts."""
    from pidreams.audio import effects
    rate = 24000
    rng = np.random.default_rng(7)
    voice = (0.3 * rng.standard_normal(rate)).astype(np.float32)
    shaper, parts, i = effects.AssistantEffect(rate, "medio"), [], 0
    for size in (1, 480, 3000, 7, 9000, 24000):
        parts.append(shaper.process(voice[i:i + size]))
        i += size
    parts.append(shaper.flush())
    assert np.allclose(np.concatenate(parts), effects.assistant(voice, rate, "medio"), atol=1e-5)


def test_efeito_aceita_so_as_intensidades_conhecidas(tmp_path):
    from pidreams.core.settings import Settings
    st = Settings(tmp_path / "settings.json")
    st.set("voice.effect", "forte")
    assert st.get("voice.effect") == "forte"
    with pytest.raises(ValueError):
        st.set("voice.effect", "robô")


def test_motor_aplica_o_efeito_pedaco_a_pedaco(monkeypatch):
    engine = tts.TTSEngine()
    engine._sample_rate = 24000
    monkeypatch.setattr(engine, "_voice_chunks", lambda text: iter([np.ones(100, np.float32), np.ones(50, np.float32)]))
    monkeypatch.setattr(tts.SETTINGS, "get", lambda key: "leve" if key == "voice.effect" else None)
    chunks = list(engine._synthesize("frase"))
    # each chunk as it comes (a streaming voice still starts at once), then the echo tail
    assert [len(c) for c in chunks] == [100, 50, int(24000 * 71 / 1000)]


class _FakePocket:
    def __init__(self, voice_file):
        self.voice_file, self.calls = voice_file, []

    def stream(self, text, stop=None):
        self.calls.append((text, stop))
        yield np.ones(1920, np.float32)
        yield np.ones(1920, np.float32)


def test_voz_padrao_e_o_pocket_em_streaming(monkeypatch):
    from pidreams.audio import pocket
    monkeypatch.setattr(pocket, "PocketVoice", _FakePocket)
    monkeypatch.setattr(models, "pocket_present", lambda: True)
    monkeypatch.setattr(tts.SETTINGS, "get", lambda key: "" if key == "voice.effect" else None)
    engine = tts.TTSEngine()
    engine._load_voice("voz-de-versao-antiga")                # resolves to the default
    assert engine._voice_name == "pocket-baritono" and engine._pocket.voice_file == "baritono.safetensors"
    assert [len(c) for c in engine._synthesize("Boa tarde.")] == [1920, 1920]   # chunk by chunk
    assert engine._pocket.calls == [("Boa tarde.", engine._interrupted)]       # interrupting stops it
    assert (pocket.VOICES_DIR / "baritono.safetensors").is_file()              # shipped with the app


def test_config_local_aponta_para_os_arquivos_baixados(monkeypatch, tmp_path):
    from pidreams.audio import pocket
    monkeypatch.setattr(pocket.paths, "models_dir", lambda kind: tmp_path)
    text = pocket._config_file().read_text(encoding="utf-8")
    assert f"weights_path: {(tmp_path / 'model.safetensors').as_posix()}" in text
    assert f"tokenizer_path: {(tmp_path / 'tokenizer.json').as_posix()}" in text
    assert "hf://" not in text                                # nothing fetched while the app runs


def test_voz_misturada_soma_os_estilos(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=_FakeKokoro))
    monkeypatch.setattr(models, "kokoro_present", lambda: True)
    engine = tts.TTSEngine()
    engine._load_voice("kokoro-alex-santa")
    assert np.allclose(engine._kokoro_voice, 2.0)                           # 0.5 * 1 + 0.5 * 3


def test_callback_de_audio_marca_o_inicio_da_fala():
    """The audio callback receives a parameter named "time": the clock must not depend on that name."""
    engine = tts.TTSEngine()
    chunk = np.ones(4096, np.float32)
    engine._play_buf.append(chunk)
    engine._captions.append((chunk, "frase"))
    engine._callback(np.zeros((2048, 1), np.float32), 2048, object(), None)
    assert engine.first_audio_at is not None and tts.SPEAKING_TEXT[0] == "frase"
