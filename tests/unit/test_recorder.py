"""Gravação do microfone."""


def test_gravacao_cancelada_antes_do_audio_volta_vazia(monkeypatch):
    import asyncio
    import contextlib

    from pidreams.audio import recorder as rec_mod

    monkeypatch.setattr(rec_mod.sd, "InputStream", lambda **_kw: contextlib.nullcontext())
    r = rec_mod.AudioRecorder.__new__(rec_mod.AudioRecorder)
    r._queue = __import__("queue").Queue()
    r._chunks_timing = lambda: (0, 10, 100)
    r._stream_kwargs = lambda: {}
    audio = asyncio.run(r.record_until_silence(cancel_check=lambda: True))
    assert audio.size == 0


def _barge_in(monkeypatch, chunks, playback):
    """Feeds `chunks` (rms values) to the barge-in watcher while the assistant plays at `playback`."""
    import asyncio
    import contextlib
    import queue

    import numpy as np

    from pidreams.audio import recorder as rec_mod

    monkeypatch.setattr(rec_mod.sd, "InputStream", lambda **_kw: contextlib.nullcontext())
    r = rec_mod.AudioRecorder.__new__(rec_mod.AudioRecorder)
    r._queue, r._threshold = queue.Queue(), 0.004
    r._echo_ratios = rec_mod.collections.deque(maxlen=80)
    r._chunks_timing = lambda: (16, 5, 400)
    r._stream_kwargs = lambda: {}
    r._flush_queue = lambda: None
    for level in chunks:
        r._queue.put(np.full(1024, level, np.float32))
    fired = []
    left = [len(chunks)]

    def cancel():
        left[0] -= 1
        return left[0] < 0 or bool(fired)
    asyncio.run(r.record_while_agent_speaks(lambda: fired.append(1), cancel_check=cancel,
                                            playback_level=lambda: playback))
    return bool(fired)


def test_eco_da_propria_voz_nao_interrompe(monkeypatch):
    # The echo is louder than the old threshold (0.004 x 2.5) the whole time, but follows the playback.
    assert not _barge_in(monkeypatch, [0.025] * 40, playback=0.1)


def test_fala_bem_acima_do_eco_interrompe(monkeypatch):
    assert _barge_in(monkeypatch, [0.025] * 20 + [0.09] * 12, playback=0.1)


def test_sem_voz_tocando_vale_o_limite_de_sempre(monkeypatch):
    assert _barge_in(monkeypatch, [0.02] * 12, playback=0.0)


def _recorder(monkeypatch, levels, threshold=0.004, max_chunks=100):
    import contextlib
    import queue

    import numpy as np

    from pidreams.audio import recorder as rec_mod

    monkeypatch.setattr(rec_mod.sd, "InputStream", lambda **_kw: contextlib.nullcontext())
    r = rec_mod.AudioRecorder.__new__(rec_mod.AudioRecorder)
    r._queue, r._threshold = queue.Queue(), threshold
    r._chunks_timing = lambda: (16, 19, max_chunks)
    r._stream_kwargs = lambda: {}
    r._flush_queue = lambda: None
    for level in levels:
        r._queue.put(np.full(1024, level, np.float32))
    return r


def test_barulho_na_calibracao_nao_esconde_a_voz(monkeypatch):
    # 1.5 s of a quiet room with a loud sound in the middle: the mean gave 0.055 and the voice never
    # crossed the threshold (2026-11-09).
    import asyncio

    r = _recorder(monkeypatch, [0.003] * 14 + [0.12] * 6 + [0.003] * 3)
    asyncio.run(r.calibrate())                # reads the queued chunks for its 1.5 s
    assert r._threshold < 0.01


def test_teto_do_limite_fica_abaixo_da_voz():
    from pidreams.audio.recorder import _threshold_from

    assert _threshold_from([0.06] * 20)[1] <= 0.02


def test_gravacao_inteira_sem_comecar_reaprende_o_limite(monkeypatch):
    import asyncio

    r = _recorder(monkeypatch, [0.003] * 70 + [0.015] * 30, threshold=0.05)
    asyncio.run(r.record_until_silence())
    assert r._threshold < 0.01
    # the voice (0.015) now starts a recording and its silence ends it
    r2 = _recorder(monkeypatch, [0.003] * 5 + [0.015] * 20 + [0.003] * 25, threshold=r._threshold)
    audio = asyncio.run(r2.record_until_silence())
    assert audio.size == (5 + 20 + 19) * 1024
