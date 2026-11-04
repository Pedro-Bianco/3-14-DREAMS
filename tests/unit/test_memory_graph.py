"""Grafo de memórias: assuntos, montagem, layout, destaque do último turno e busca."""

import numpy as np

from pidreams.memory import graph, topics, worker
from pidreams.memory.graph import Layout, build, matches, used_nodes


# ── assuntos ──

def test_parser_de_assuntos_fora_de_ordem_invalido_e_faltando():
    raw = "2. Trabalho\n1. familia\n4. astrologia\n"
    assert topics.parse_topics(raw, 4) == ["família", "trabalho", "outros", "outros"]


def test_prompt_numera_as_memorias():
    p = topics.prompt_for(["O usuário tem uma gata", "O usuário corre"])
    assert "1. O usuário tem uma gata" in p and "2. O usuário corre" in p and "família" in p


class _Store:
    def __init__(self, pending):
        self.pending, self.tagged = pending, {}

    def untagged(self):
        return self.pending

    def set_topics(self, found):
        self.tagged.update(found)


def _worker(store, reply, monkeypatch):
    w = worker.MemoryWorker.__new__(worker.MemoryWorker)
    w._store, w._next_tagging = store, 0.0
    calls = []

    class _Client:
        def chat(self, **kw):
            calls.append(kw)
            return type("R", (), {"message": type("M", (), {"content": reply})()})()
    w._client = _Client()
    return w, calls


def test_perfil_ganha_assunto_sem_chamar_o_modelo(monkeypatch):
    store = _Store([{"id": 1, "text": "O usuário quer ser chamado de chefe", "kind": "perfil"}])
    w, calls = _worker(store, "", monkeypatch)
    w._tag_topics()
    assert store.tagged == {1: "perfil"} and calls == []


def test_fatos_sem_assunto_sao_marcados_em_lote(monkeypatch):
    store = _Store([{"id": 1, "text": "O usuário tem uma gata", "kind": "fato"},
                    {"id": 2, "text": "O usuário é engenheiro", "kind": "fato"}])
    w, calls = _worker(store, "1. animais\n2. trabalho", monkeypatch)
    w._tag_topics()
    assert store.tagged == {1: "animais", 2: "trabalho"} and len(calls) == 1


# ── montagem ──

def _mem(i, text, topic, vec, kind="fato"):
    return {"id": i, "text": text, "kind": kind, "topic": topic, "ts": "2026-10-31", "vector": vec}


MEMS = [
    _mem(1, "A filha do usuário se chama Bia", "família", [1, 0, 0]),
    _mem(2, "A filha do usuário tem cinco anos", "família", [0.9, 0.1, 0]),
    _mem(3, "O usuário é casado", "família", [0, 0, 1]),
    _mem(4, "O usuário é engenheiro", "trabalho", [0, 1, 0]),
    _mem(5, "O usuário quer ser chamado de chefe", None, [0, 0, 1], kind="perfil"),
    _mem(6, "O usuário tem uma gata", None, [1, 1, 0]),
]


def test_memorias_agrupadas_por_assunto_com_perfil_e_sem_assunto():
    g = build(MEMS)
    names = {n.label for n in g.nodes if n.kind == "topic"}
    assert names == {"Família", "Trabalho", "Perfil", "Sem assunto"}
    idx = g.index()
    belongs = {(a, b) for a, b, k in g.edges if k == "belongs"}
    assert (idx["t:família"], idx["m:1"]) in belongs and (idx["t:perfil"], idx["m:5"]) in belongs


def test_cada_memoria_liga_a_mais_parecida_do_mesmo_assunto():
    g = build(MEMS)
    idx = g.index()
    similar = {(a, b) for a, b, k in g.edges if k == "similar"}
    assert (idx["m:1"], idx["m:2"]) in similar                    # Bia ↔ cinco anos
    assert all(g.nodes[a].topic == g.nodes[b].topic for a, b in similar)


def test_documento_fechado_sem_partes_e_parte_usada_aparece():
    docs = [{"doc_id": "d1", "source": "contrato.pdf", "count": 400}]
    g = build(MEMS, docs)
    assert sum(n.kind == "piece" for n in g.nodes) == 0
    g = build(MEMS, docs, [{"doc_id": "d1", "source": "contrato.pdf", "where": "p. 3", "text": "multa de 2%"}])
    piece = [n for n in g.nodes if n.kind == "piece"]
    assert len(piece) == 1 and piece[0].key == graph.piece_key("contrato.pdf", "p. 3")


# ── layout ──

def test_layout_acomoda_para_e_aproxima_o_mesmo_assunto():
    rng = np.random.default_rng(0)
    mems = [_mem(i, f"memória {i}", ("família", "trabalho", "lazer")[i % 3], rng.normal(size=8)) for i in range(60)]
    g = build(mems)
    lay = Layout(g)
    lay.settle(400)
    assert lay.settled
    pos, idx = lay.pos, g.index()
    same, other = [], []
    for i in range(60):
        for j in range(i + 1, 60):
            dist = np.linalg.norm(pos[idx[f"m:{i}"]] - pos[idx[f"m:{j}"]])
            (same if i % 3 == j % 3 else other).append(dist)
    assert np.mean(same) < np.mean(other) * 0.6


def test_memoria_nova_nao_refaz_o_desenho():
    g = build(MEMS)
    first = Layout(g)
    first.settle(400)
    before = first.positions()
    g2 = build(MEMS + [_mem(7, "O usuário joga xadrez", "lazer", [0, 1, 1])])
    second = Layout(g2, previous=before)
    assert second.heat < first.heat or second.heat <= 6.0
    assert np.allclose(second.pos[g2.index()["m:1"]], before["m:1"])


# ── destaque e busca ──

def test_destaque_do_ultimo_turno():
    docs = [{"doc_id": "d1", "source": "contrato.pdf", "count": 4}]
    g = build(MEMS, docs, [{"doc_id": "d1", "source": "contrato.pdf", "where": "p. 3", "text": "multa"}])
    used = {"profile": ["O usuário quer ser chamado de chefe"], "memories": ["O usuário tem uma gata"],
            "pieces": [["contrato.pdf", "p. 3"]]}
    idx = g.index()
    assert used_nodes(g, used) == {idx["m:5"], idx["m:6"], idx[graph.piece_key("contrato.pdf", "p. 3")]}
    assert used_nodes(g, {"profile": [], "memories": [], "pieces": []}) == set()


def test_busca_sem_acento_e_maiuscula():
    g = build(MEMS)
    found = {g.nodes[i].key for i in matches(g, "FILHA")}
    assert found == {"m:1", "m:2"}
    assert {g.nodes[i].key for i in matches(g, "familia")} == {"t:família"}
