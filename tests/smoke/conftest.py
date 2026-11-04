"""Simulações compartilhadas pelos testes de fumaça.

Nenhum teste aqui toca câmera, microfone, alto-falante, GPU ou Ollama de verdade.
Modelos locais já baixados (vozes Kokoro,
Whisper) podem ser usados; se faltarem, o teste é pulado em vez de baixar.
"""

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]

# Nada de download durante os testes.
os.environ.setdefault("HF_HUB_OFFLINE", "1")


# ── Embeddings ────────────────────────────────────────────────────────────────

class FakeEmbedModel:
    """Vetores determinísticos por saco de palavras: textos com palavras em comum
    ficam próximos, o que basta para testar busca sem baixar o e5-large."""

    DIM = 64

    def embed(self, texts, batch_size=None):
        for text in texts:
            v = np.zeros(self.DIM, dtype=np.float32)
            for word in text.lower().split():
                v[hash(word.strip(".,:;!?")) % self.DIM] += 1.0
            yield v + 1e-3


@pytest.fixture
def fake_embedder():
    from pidreams.memory.embedder import FastEmbedManager

    emb = FastEmbedManager.__new__(FastEmbedManager)
    emb.model_name = "fake"
    emb.model = FakeEmbedModel()
    emb._vector_size = None
    emb._is_e5 = False
    return emb


# ── Câmera ────────────────────────────────────────────────────────────────────

class FakeVideoCapture:
    """Quadros sintéticos com texto e um círculo que se move (mesmo padrão usado
    para validar a janela da câmera em 2026-10-16)."""

    def __init__(self, *_args, **_kwargs):
        self._open = True
        self._t0 = time.time()

    def isOpened(self):
        return self._open

    def read(self):
        import cv2

        time.sleep(0.01)
        img = np.full((240, 320, 3), (60, 40, 20), np.uint8)
        x = int(160 + 80 * np.sin(time.time() - self._t0))
        cv2.circle(img, (x, 150), 30, (0, 0, 220), -1)
        cv2.putText(img, "PI 314", (90, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        return True, img

    def release(self):
        self._open = False


@pytest.fixture
def fake_camera(monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "VideoCapture", FakeVideoCapture)
    return FakeVideoCapture


# ── Áudio ─────────────────────────────────────────────────────────────────────

class FakeInputStream:
    """Entrega à callback os blocos de `FakeInputStream.blocos`, depois silêncio."""

    blocks: list = []

    def __init__(self, callback=None, blocksize=1024, channels=1, **_kw):
        self._cb, self._n, self._ch = callback, blocksize, channels
        self._stop = threading.Event()
        # Como o sounddevice real: o stream e a função de callback se referenciam
        # (ciclo), então o stream só é liberado pela coleta de lixo.
        self._callback_ptr = lambda *a: self._cb(*a)

    def __enter__(self):
        def run():
            queue = list(FakeInputStream.blocks)
            while not self._stop.is_set():
                block = queue.pop(0) if queue else np.zeros((self._n, self._ch), np.float32)
                self._cb(block, self._n, None, None)
                time.sleep(0.002)

        threading.Thread(target=run, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._stop.set()

    # uso sem "with" (medidor de nível do assistente de primeiro uso)
    def start(self):
        self.__enter__()

    def stop(self):
        self._stop.set()

    close = stop


class FakeOutputStream:
    """Chama a callback de reprodução como a placa de som faria."""

    def __init__(self, callback=None, blocksize=2048, channels=1, **_kw):
        self._cb, self._n, self._ch = callback, blocksize, channels
        self._stop = threading.Event()

    def start(self):
        def run():
            while not self._stop.is_set():
                self._cb(np.zeros((self._n, self._ch), np.float32), self._n, None, None)
                time.sleep(0.005)

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def close(self):
        self._stop.set()


@pytest.fixture
def fake_sound(monkeypatch):
    import sounddevice as sd

    monkeypatch.setattr(sd, "InputStream", FakeInputStream)
    monkeypatch.setattr(sd, "OutputStream", FakeOutputStream)
    FakeInputStream.blocks = []
    return SimpleNamespace(input=FakeInputStream, output=FakeOutputStream)


# ── Ollama ────────────────────────────────────────────────────────────────────

def reply(content="", tool_calls=()):
    calls = [SimpleNamespace(function=SimpleNamespace(name=n, arguments=a)) for n, a in tool_calls]
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls or None))


class FakeOllamaClient:
    """Devolve as respostas programadas, na ordem, e guarda as chamadas recebidas."""

    def __init__(self, replies):
        self._answers = list(replies)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self._answers.pop(0)

    def generate(self, **kwargs):
        return SimpleNamespace(response="")

    def ps(self):
        return SimpleNamespace(models=[])


# ── Modelos locais opcionais ──────────────────────────────────────────────────

def voice_or_skip():
    """The voices downloaded (Kokoro); skipped when they are not on this machine."""
    from pidreams.hardware import models

    if not models.kokoro_present():
        pytest.skip("vozes Kokoro não baixadas")


def speech_16k(text: str) -> np.ndarray:
    from pidreams.audio import tts

    audio = tts.sample("kokoro-alex", text)
    n = int(len(audio) * 16000 / tts.KOKORO_RATE)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


# ── Tk ────────────────────────────────────────────────────────────────────────

# Mensagens do Tk quando ele não consegue ler os próprios arquivos ao iniciar.
_TK_STARTUP_ERRORS = ("usable tk.tcl", "usable init.tcl", "tcl_findLibrary", "couldn't read file")


def create_window(factory, attempts: int = 4):
    """Cria uma janela Tk tolerando a falha intermitente de leitura dos arquivos
    .tcl (antivírus verificando o arquivo enquanto vários testes abrem janelas em
    sequência). Só esse erro é repetido; qualquer outro falha na hora."""
    import tkinter

    for attempt in range(attempts):
        try:
            return factory()
        except tkinter.TclError as e:
            startup = any(m in str(e) for m in _TK_STARTUP_ERRORS)
            if not startup or attempt == attempts - 1:
                raise
            time.sleep(0.5)
