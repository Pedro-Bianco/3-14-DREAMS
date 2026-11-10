"""Monitoramento: each layer shows what is on disk at once and is updated when the source answers."""

from pidreams.monitor import sources
from pidreams.ui.monitor_view import MonitorView


class _View:
    """Just what _load_layer touches; Tk's after(0, fn) runs fn right away."""

    def __init__(self):
        self.notes, self.shown = {}, []

    def after(self, _ms, fn):
        fn()

    def _note(self, name, text):
        self.notes[name] = text

    _describe = staticmethod(MonitorView._describe)


def _load(monkeypatch, age, max_age=300):
    monkeypatch.setattr(sources, "cache_age", lambda _name: age)
    view, calls = _View(), []

    def fetch(stale_ok):
        calls.append(stale_ok)
        return ["velho"] if stale_ok else ["novo", "novo"]
    MonitorView._load_layer(view, "terremotos", "quakes", max_age, view.shown.append, fetch)
    return view, calls


def test_copia_vencida_aparece_na_hora_e_depois_e_trocada(monkeypatch):
    view, calls = _load(monkeypatch, age=3600)
    assert calls == [True, False]
    assert view.shown == [["velho"], ["novo", "novo"]]
    assert view.notes["terremotos"] == "2 terremotos"


def test_copia_em_dia_nao_busca_duas_vezes(monkeypatch):
    _view, calls = _load(monkeypatch, age=10)
    assert calls == [False]


def test_sem_copia_baixa_uma_vez(monkeypatch):
    _view, calls = _load(monkeypatch, age=None)
    assert calls == [False]


def test_fonte_fora_do_ar_vira_aviso(monkeypatch):
    monkeypatch.setattr(sources, "cache_age", lambda _name: None)
    view = _View()

    def fetch(_stale_ok):
        raise sources.SourceError("Não consegui os terremotos agora.")
    MonitorView._load_layer(view, "terremotos", "quakes", 300, view.shown.append, fetch)
    assert view.shown == [] and view.notes["terremotos"] == "Não consegui os terremotos agora."
