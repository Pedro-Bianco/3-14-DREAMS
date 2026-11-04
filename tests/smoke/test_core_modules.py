"""Um teste de fumaça por módulo do núcleo, sem hardware."""

import asyncio
import time

import numpy as np
import pytest
from qdrant_client import QdrantClient

from tests.smoke.conftest import FakeOllamaClient, speech_16k, reply, voice_or_skip


def test_memoria_ltm_e_kb_gravam_e_recuperam(monkeypatch, fake_embedder):
    import pidreams.memory.store as store_mod
    from pidreams.memory.kb_store import KBStore

    client = QdrantClient(location=":memory:")
    monkeypatch.setattr(store_mod, "QdrantClient", lambda **_kw: client)
    monkeypatch.setattr(store_mod, "FastEmbedManager", lambda *_a, **_kw: fake_embedder)

    ltm = store_mod.LTMStore()
    assert ltm.available
    ltm.upsert("O usuário gosta de café sem açúcar")
    assert any("café" in fact for fact in ltm.search("gosta de café", score_min=0.1))

    kb = KBStore(client=client, embedder=fake_embedder)
    assert kb.available
    kb.ingest("A senha do wifi da sala é girassol. O roteador fica na estante.", source_name="casa")
    assert any("girassol" in snippet for snippet in kb.search("senha do wifi", score_min=0.1))


def test_transcricao_entende_fala_e_ignora_silencio():
    from pidreams.stt.transcriber import Transcriber

    voice_or_skip()
    try:
        stt = Transcriber()
    except Exception as e:  # modelo Whisper não baixado e download bloqueado
        pytest.skip(f"Whisper indisponível offline: {e}")

    text = stt.transcribe(speech_16k("Abre o bloco de notas, por favor.")).lower()
    assert "bloco de notas" in text
    assert stt.transcribe(np.zeros(16000 * 2, np.float32)) == ""


def test_tts_preenche_nivel_da_voz(fake_sound):
    from pidreams.audio import tts as tts_mod

    voice_or_skip()
    engine = tts_mod.TTSEngine()
    engine.start()
    tts_mod.VOICE_LEVEL[0] = 0.0

    async def speak():
        await engine.speak("Olá, tudo certo por aqui.")
        end = time.time() + 20
        while tts_mod.VOICE_LEVEL[0] == 0.0 and time.time() < end:
            await asyncio.sleep(0.01)
        peak = tts_mod.VOICE_LEVEL[0]
        await engine.shutdown()
        return peak

    assert asyncio.run(speak()) > 0.0


def test_gravador_grava_ate_o_silencio(fake_sound):
    from pidreams.audio.recorder import AudioRecorder
    from pidreams.core.config import CONFIG

    speech = (0.2 * np.sin(np.linspace(0, 400, CONFIG.chunk_size))).astype(np.float32).reshape(-1, 1)
    fake_sound.input.blocks = [speech] * 10

    audio = asyncio.run(AudioRecorder(mic_device_ref=[None]).record_until_silence())
    assert len(audio) >= 10 * CONFIG.chunk_size


def test_camera_entrega_quadros_e_foto(fake_camera):
    from pidreams.camera.stream import CameraStream

    cam = CameraStream()
    triggers = []
    cam.on_snapshot(lambda: triggers.append(1))
    cam.start()
    try:
        end = time.time() + 3
        while cam.latest() is None and time.time() < end:
            time.sleep(0.01)
        assert cam.latest() is not None
        assert cam.snapshot().shape == (240, 320, 3)
        assert triggers == [1]
    finally:
        cam.stop()
    assert not cam.running


def test_agente_executa_ferramenta_e_responde(monkeypatch):
    import pyperclip

    from pidreams.agent.llm import LLMAgent

    copied = []
    monkeypatch.setattr(pyperclip, "copy", copied.append)

    agent = LLMAgent()
    agent._client = FakeOllamaClient([
        reply(tool_calls=[("clipboard_write", {"text": "olá mundo"})]),
        reply(content="Copiei para a área de transferência."),
    ])

    async def chat_turn():
        return [s async for s in agent.chat_streaming("copia olá mundo")]

    phrases = asyncio.run(chat_turn())
    assert copied == ["olá mundo"]
    assert phrases == ["Copiei para a área de transferência."]
    assert len(agent._client.calls) == 2
