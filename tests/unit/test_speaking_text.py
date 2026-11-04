"""Legenda: a frase é marcada quando o áudio dela começa a tocar, não quando o texto chega."""

import collections
import queue
import threading

import numpy as np

from pidreams.audio import tts


def _motor_sem_voz():
    """Só o necessário para o callback de áudio (sem carregar a voz nem abrir a placa de som)."""
    engine = object.__new__(tts.TTSEngine)
    engine._play_buf, engine._captions = collections.deque(), collections.deque()
    engine._buf_lock = threading.Lock()
    engine._current, engine._pos = None, 0
    engine._volume_ref = [1.0]
    engine._interrupted = threading.Event()
    engine._synth_q = queue.Queue()
    return engine


def _tocar(engine, quadros):
    out = np.zeros((quadros, 1), dtype=np.float32)
    engine._callback(out, quadros, None, None)


def _enfileirar(engine, frase, pedacos, tamanho=100):
    for i in range(pedacos):
        chunk = np.full(tamanho, 0.1, dtype=np.float32)
        engine._play_buf.append(chunk)
        if i == 0:
            engine._captions.append((chunk, frase))


def test_legenda_troca_quando_cada_frase_comeca_a_tocar():
    engine = _motor_sem_voz()
    tts.SPEAKING_TEXT[0] = ""
    _enfileirar(engine, "Primeira frase.", pedacos=2)
    _enfileirar(engine, "Segunda frase.", pedacos=1)
    _tocar(engine, 100)
    assert tts.SPEAKING_TEXT[0] == "Primeira frase."
    _tocar(engine, 100)                       # segundo pedaço da mesma frase
    assert tts.SPEAKING_TEXT[0] == "Primeira frase."
    _tocar(engine, 100)
    assert tts.SPEAKING_TEXT[0] == "Segunda frase."


def test_legenda_some_no_silencio_e_na_interrupcao():
    engine = _motor_sem_voz()
    _enfileirar(engine, "Uma frase.", pedacos=1)
    _tocar(engine, 100)
    _tocar(engine, 100)                       # nada mais na fila
    assert tts.SPEAKING_TEXT[0] == ""
    _enfileirar(engine, "Outra frase.", pedacos=3)
    _tocar(engine, 100)
    assert tts.SPEAKING_TEXT[0] == "Outra frase."
    engine.interrupt()
    assert tts.SPEAKING_TEXT[0] == "" and not engine._captions
