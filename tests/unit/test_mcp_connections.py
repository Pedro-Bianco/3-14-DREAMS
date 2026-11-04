"""Conexões MCP com o servidor de teste real (processo por stdio): estados, ferramentas,
corte, tempo-limite, falhas e a ferramenta usar_<id> na conversa principal."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from pidreams.agent import tools
from pidreams.mcp.connections import CUTOFF, Connections

SERVER = str(Path(__file__).resolve().parents[1] / "fixtures" / "test_server.py")


def _wait(c, id_, until=20):
    end = time.time() + until
    while c.state(id_)[0] == "iniciando" and time.time() < end:
        time.sleep(0.05)
    return c.state(id_)


@pytest.fixture
def connections():
    notices = []
    c = Connections(on_notice=notices.append, limit_s=2)
    c.notices = notices
    yield c
    c.stop_all()


def _start_test(c, *args, **kw):
    c.start_connection("teste", "Teste", StdioServerParameters(command=sys.executable, args=[SERVER, *args]), **kw)
    return _wait(c, "teste")


def test_conecta_e_lista_com_anotacoes(connections):
    assert _start_test(connections) == ("conectado", "")
    read_only = {f.name: f.read_only for f in connections.tools("teste")}
    assert read_only == {"read_note": True, "write_note": False, "unannotated": False,
                          "slow": True, "large": True}
    assert connections.call("teste", "read_note", {"title": "compras"}) == "pão, leite e café"
    assert "Guarda e lê notas" in connections.instructions_for("teste")


def test_resultado_grande_e_cortado(connections):
    _start_test(connections)
    text = connections.call("teste", "large", {})
    assert text.startswith("linha fictícia") and f"cortado: {CUTOFF} de" in text


def test_chamada_lenta_cancela_no_limite_com_aviso(connections):
    _start_test(connections)
    start_at = time.time()
    assert "não respondeu" in connections.call("teste", "slow", {"seconds": 30})
    assert time.time() - start_at < 5
    assert connections.notices[-1]["code"] == "mcp_teste"


def test_servidor_que_nao_inicia_vira_erro_e_aviso(connections):
    start_at = time.time()
    state, reason_text = _start_test(connections, "--quebrar")
    assert state == "erro" and reason_text
    assert time.time() - start_at < 10
    assert connections.notices[-1]["code"] == "mcp_teste"
    connections.start_connection("nada", "Nada", StdioServerParameters(command="comando_que_nao_existe_xyz"))
    state, reason_text = _wait(connections, "nada")
    assert state == "erro" and "não encontrei" in reason_text


def test_servidor_que_cai_vira_aviso_em_ate_10s(connections):
    _start_test(connections)
    children = [p for p in __import__("psutil").Process().children(recursive=True)
              if SERVER in " ".join(p.cmdline())]
    assert children
    for p in children:
        p.kill()
    end = time.time() + 10
    while connections.state("teste")[0] == "conectado" and time.time() < end:
        time.sleep(0.1)
    assert connections.state("teste")[0] == "erro"
    assert connections.notices[-1]["code"] == "mcp_teste"


def test_usar_aparece_so_com_o_servidor_conectado(connections, monkeypatch):
    monkeypatch.setattr(tools, "_MCP", dict(tools._MCP))
    tools.configure_mcp(connections, lambda _briefing: False)      # the app's real path
    names = lambda **kw: {s["function"]["name"] for s in tools.active_tool_schemas(**kw)}
    assert "usar_teste" not in names()
    _start_test(connections, description="Lê e grava notas.")
    assert "usar_teste" in names()
    connections.stop_connection("teste")
    assert "usar_teste" not in names()
    assert "não está ligada" in tools.dispatch_tool("usar_teste", {"pedido": "lê a nota"})


def test_subconjunto_dos_prontos(connections):
    _start_test(connections, only={"read_note"})
    assert [f.name for f in connections.tools("teste")] == ["read_note"]
    assert len(connections.tools("teste", all_items=True)) == 5


def test_conexao_saudavel_continua_depois_do_sinal_de_vida():
    """Regressão: o ping saiu do protocolo e derrubava conexões saudáveis em 5 s."""
    c = Connections(limit_s=2)
    try:
        _start_test(c)
        time.sleep(12)
        assert c.state("teste") == ("conectado", "")
    finally:
        c.stop_all()


def test_builtin_servers_that_need_node_ask_for_the_install_first(monkeypatch):
    from pidreams.mcp import builtin, runtime

    monkeypatch.setattr(runtime, "is_ready", lambda: False)
    assert builtin.needs_install("arquivos") and not builtin.needs_install("gmail")
    monkeypatch.setattr(runtime, "is_ready", lambda: True)
    assert not builtin.needs_install("arquivos")
