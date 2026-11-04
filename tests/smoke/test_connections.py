"""Aba Conexões no app: adicionar, ver cair e remover um servidor."""

import copy
import sys
import time
from pathlib import Path

import psutil
import pytest

from pidreams.ui.panels.new_connection import make_id, validate
from tests.smoke.conftest import create_window

SERVER = str(Path(__file__).resolve().parents[1] / "fixtures" / "test_server.py")


@pytest.mark.parametrize("name, command, address, error", [
    ("", "x.exe", "", "nome"),
    ("Notas", "", "", "comando OU"),
    ("Notas", "x.exe", "http://127.0.0.1:8000/mcp", "só um"),
    ("Notas", "", "https://exemplo.com/mcp", "deste computador"),
    ("Arquivos", "x.exe", "", "Já existe"),
])
def test_validacao_da_nova_conexao(name, command, address, error):
    with pytest.raises(ValueError, match=error):
        validate(name, command, address, {"arquivos"})


def test_comando_com_argumentos_e_aspas():
    id_, fields = validate("Minhas Notas", '"C:\\Program Files\\notas\\notas.exe" --pasta "D:\\Notas X"', "", set())
    assert id_ == "minhas_notas" and make_id("Ação Rápida") == "acao_rapida"
    assert fields["comando"] == "C:\\Program Files\\notas\\notas.exe"
    assert fields["argumentos"] == ["--pasta", "D:\\Notas X"]


def test_adicionar_cair_e_remover(monkeypatch):
    from pidreams.core.settings import SETTINGS
    from pidreams.ui import main_window, widgets

    monkeypatch.setattr(widgets.WeatherFetcher, "_run", lambda self: None)
    monkeypatch.setattr(SETTINGS, "save", lambda: None)                 # nunca grava o arquivo real
    monkeypatch.setitem(SETTINGS.data, "mcp", copy.deepcopy(SETTINGS.data.get("mcp", {})))
    app = create_window(main_window.AgentApp)
    notices = []
    show = app._notices.show
    monkeypatch.setattr(app._notices, "show", lambda a: (notices.append(a), show(a)))
    app._process_events()                       # o que app.run() liga: avisos chegam pela fila

    def wait(condition, until):
        end = time.time() + until
        while not condition() and time.time() < end:
            app.root.update()
            time.sleep(0.05)
        return condition()

    try:
        start_at = time.time()
        app._save_new("teste", {"nome": "Teste", "comando": sys.executable, "argumentos": [SERVER],
                                   "endereco": None, "descricao": "Notas de teste."})
        assert wait(lambda: app._connections.state("teste")[0] == "conectado", 15)
        assert time.time() - start_at < 15
        assert SETTINGS.get("mcp.servers")["teste"]["ligado"] is True

        for p in psutil.Process().children(recursive=True):
            if SERVER in " ".join(p.cmdline()):
                p.kill()
        start_at = time.time()
        assert wait(lambda: any(a["code"] == "mcp_teste" for a in notices), 10)
        assert app._connections.state("teste")[0] == "erro"

        app._remove_connection("teste")
        assert "teste" not in SETTINGS.get("mcp.servers")
        assert app._connections.state("teste")[0] == "desligado"
    finally:
        app._connections.stop_all()
        app._sphere.stop()
        app.root.destroy()
