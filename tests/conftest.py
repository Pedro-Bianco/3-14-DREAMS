"""Configuração comum a todos os testes."""

import gc
import os
import time
import tkinter

import pytest

from pidreams.core import paths

# What Tk says when it cannot read its own .tcl files while starting.
_TK_STARTUP_ERRORS = ("usable tk.tcl", "usable init.tcl", "tcl_findLibrary", "couldn't read file")


@pytest.fixture(autouse=True, scope="session")
def _tk_retries_startup():
    """Opening many Tk windows in a row sometimes fails to read init.tcl ("couldn't read file ...:
    No error"), on this machine about once every 10 runs of the suite. Only that startup error is
    retried; any other fails at once."""
    original = tkinter.Tk.__init__

    def init(self, *args, **kwargs):
        for attempt in range(4):
            try:
                return original(self, *args, **kwargs)
            except tkinter.TclError as e:
                if attempt == 3 or not any(m in str(e) for m in _TK_STARTUP_ERRORS):
                    raise
                time.sleep(0.5)

    tkinter.Tk.__init__ = init
    yield
    tkinter.Tk.__init__ = original


@pytest.fixture(autouse=True)
def _tk_collected_on_main_thread():
    """Os testes criam e destroem muitas janelas Tk. Se o lixo delas for recolhido
    depois por uma thread secundária, o Tcl entra em pânico e derruba o processo
    (0x80000003, visto em 2026-10-19). Coletar aqui, na thread principal, evita."""
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _never_write_real_data(monkeypatch):
    """Nenhum teste pode alterar o settings.json/secrets.bin do usuário: em
    2026-10-19 um teste gravou no arquivo real e apagou o microfone escolhido."""
    real_dispatch = paths.settings_file()
    before = real_dispatch.read_bytes() if real_dispatch.is_file() else None
    marker = os.path.getmtime(real_dispatch) if real_dispatch.is_file() else None
    yield
    after_val = os.path.getmtime(real_dispatch) if real_dispatch.is_file() else None
    if marker != after_val:
        if before is not None:
            real_dispatch.write_bytes(before)           # devolve o arquivo do usuário intacto
        pytest.fail(f"o teste alterou o settings.json real ({real_dispatch})")
