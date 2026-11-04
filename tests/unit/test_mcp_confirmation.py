"""Confirmação antes de alterar: só "sim" explícito executa."""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import StdioServerParameters

from pidreams.mcp import confirmation, server_turn
from pidreams.mcp.connections import Connections

SERVER = str(Path(__file__).resolve().parents[1] / "fixtures" / "test_server.py")


@pytest.mark.parametrize("speech, yes", [
    ("sim", True), ("Sim, pode.", True), ("pode", True), ("confirma", True), ("isso", True),
    ("não", False), ("cancela", False), ("sim mas antes me diz que horas são agora", False),
    ("simplesmente não", False), ("", False), (None, False), ("qual é o tempo hoje?", False),
])
def test_so_sim_explicito_e_curto_confirma(speech, yes):
    assert confirmation.is_yes(speech) is yes


def _confirmer(spoken_reply=None, delay=0.0, deadline=1.0):
    questions, closed = [], []

    def listen(cancel, _deadline):
        if delay:
            cancel.wait(delay)
        return spoken_reply

    return confirmation.Confirmer(questions.append, listen, lambda: closed.append(1), deadline), questions, closed


def test_fala_botao_e_prazo():
    c, questions, closed = _confirmer("sim")
    assert c("Teste: gravar nota") is True and questions == ["Teste: gravar nota"] and closed
    c, *_ = _confirmer("pode deixar, mas não agora não")
    assert c("x") is False
    c, *_ = _confirmer(delay=5, deadline=0.5)                    # ninguém responde
    start_at = time.time()
    assert c("x") is False and time.time() - start_at < 2
    c, *_ = _confirmer(delay=5, deadline=3)
    threading.Timer(0.2, lambda: confirmation.answer(True)).start()
    assert c("x") is True                                         # botão CONFIRMAR
    c, *_ = _confirmer(delay=5, deadline=3)
    threading.Timer(0.2, lambda: confirmation.answer(False)).start()
    assert c("x") is False                                        # botão CANCELAR
    confirmation.answer(True)                                   # clique fora de confirmação
    c, *_ = _confirmer(delay=5, deadline=0.5)
    assert c("x") is False                                        # não vale para a próxima


def _calling_model(tool, arguments):
    """Cliente Ollama falso: chama a ferramenta uma vez e depois responde em texto."""
    replies = iter([
        SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name=tool, arguments=arguments))])),
        SimpleNamespace(message=SimpleNamespace(content="Feito.", tool_calls=None)),
    ])
    return lambda **_kw: SimpleNamespace(chat=lambda **_k: next(replies))


@pytest.fixture(scope="module")
def connections():
    c = Connections(limit_s=5)
    c.start_connection("teste", "Teste", StdioServerParameters(command=sys.executable, args=[SERVER]))
    end = time.time() + 20
    while c.state("teste")[0] == "iniciando" and time.time() < end:
        time.sleep(0.05)
    yield c
    c.stop_all()


@pytest.mark.parametrize("tool, arguments, reply, runs", [
    ("read_note", {"title": "compras"}, None, True),               # leitura: nem pergunta
    ("write_note", {"title": "t1", "text": "novo"}, False, False),
    ("write_note", {"title": "t2", "text": "novo"}, True, True),
    ("unannotated", {"title": "compras"}, False, False),          # sem anotação = altera
])
def test_turno_so_executa_alteracao_confirmada(connections, monkeypatch, tool, arguments, reply, runs):
    monkeypatch.setattr(server_turn.ollama, "Client", _calling_model(tool, arguments))
    questions, results = [], []
    call = connections.call
    monkeypatch.setattr(connections, "call", lambda *a: results.append(a) or call(*a))

    def confirm(briefing):
        questions.append(briefing)
        return reply

    text = server_turn.execute(connections, "teste", "Teste", "pedido", "", connections.tools("teste"), confirm)
    assert text == "Feito." if reply is not False else text.startswith("Não foi feito, porque você não confirmou")
    assert bool(questions) is (reply is not None)
    assert bool(results) is runs
    if questions:
        assert questions[0].startswith("Teste: ") and len(questions[0]) <= 160


def test_resumo_mostra_so_o_nome_dos_arquivos():
    text = server_turn.briefing("Arquivos", "move_file", {
        "source": r"D:\Pastas liberadas\Casa\Downloads\fatura_luz_outubro.pdf",
        "destination": "D:\\Pastas liberadas\\Casa\\Documentos\\"})
    assert text == "Arquivos: move file — fatura_luz_outubro.pdf → Documentos"
    assert "http://127.0.0.1:8765/" in server_turn.briefing("Navegador", "browser_navigate", {"url": "http://127.0.0.1:8765/"})


def test_modelo_travado_repetindo_nao_derruba_a_resposta(connections, monkeypatch):
    """Ollama aborta com "token repeat limit reached" (visto no app real): uma nova tentativa
    e, se travar de novo, uma frase legível em vez de exceção."""
    attempts = []

    def stuck(**_k):
        attempts.append(_k["options"]["temperature"])
        raise server_turn.ollama.ResponseError("prediction aborted, token repeat limit reached")

    monkeypatch.setattr(server_turn.ollama, "Client", lambda **_kw: SimpleNamespace(chat=stuck))
    text = server_turn.execute(connections, "teste", "Teste", "pedido", "", connections.tools("teste"), lambda r: True)
    assert "travou" in text and attempts == [0, 0.3]
