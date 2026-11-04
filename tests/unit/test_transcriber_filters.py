"""Filtro de alucinações do Whisper: ruído e frases-fantasma não viram pedido."""

from types import SimpleNamespace

import numpy as np

from pidreams.stt.transcriber import Transcriber, _ghost


def _sec(text, no_speech=0.1, logprob=-0.2, compression=1.2):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob,
                           compression_ratio=compression)


AUDIO = np.zeros(16000, np.float32)


def _transcriber(segments):
    t = Transcriber.__new__(Transcriber)   # sem carregar o modelo
    info = SimpleNamespace(duration=1.0, duration_after_vad=1.0)
    t.model = SimpleNamespace(transcribe=lambda *_a, **_kw: (iter(segments), info))
    return t


def test_frases_fantasma_com_e_sem_acento():
    assert _ghost("Se inscreva no canal e ative o sininho")
    assert _ghost("OBRIGADO POR ASSISTIR")
    assert _ghost("até o próximo vídeo")
    assert _ghost("ate o proximo video")
    assert not _ghost("Me diz a previsão do tempo")


def test_segmentos_sem_fala_repetitivos_ou_fantasma_sao_descartados():
    t = _transcriber([
        _sec("Abre o bloco de notas."),
        _sec("hmm", no_speech=0.9, logprob=-1.0),                     # silêncio
        _sec("canal canal canal canal canal", compression=3.0),        # repetição
        _sec("Legendas pela comunidade Amara.org"),                   # fantasma
        _sec("por favor."),
    ])
    assert t.transcribe(AUDIO) == "Abre o bloco de notas. por favor."


def test_so_ruido_vira_texto_vazio():
    assert _transcriber([_sec("Obrigado por assistir!")]).transcribe(AUDIO) == ""
