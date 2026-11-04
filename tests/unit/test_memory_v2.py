"""Memória de longo prazo: categorias da extração, consolidação com apagar e perfil."""

import pytest
from qdrant_client import QdrantClient

from pidreams.memory import updater, worker
from pidreams.memory.updater import parse_decision
from pidreams.memory.worker import parse_facts

CANDIDATOS = [{"id": 11, "text": "O usuário mora em Recife", "score": 0.8}, {"id": 22, "text": "O usuário tem um carro", "score": 0.78},
              {"id": 33, "text": "O usuário gosta de surfar", "score": 0.75}]


def test_categorias_da_extracao():
    raw = ("PERFIL: O usuário quer ser chamado de chefe\nFATO: O usuário mora em Cidade Exemplo desde 2018\n"
           "DEIXOU: O usuário vendeu a moto\n- O usuário tem uma gata chamada Mel\nNULO\nPERFIL: curto")
    assert parse_facts(raw) == [("perfil", "O usuário quer ser chamado de chefe"),
                                ("fato", "O usuário mora em Cidade Exemplo desde 2018"),
                                ("deixou", "O usuário vendeu a moto"),
                                ("fato", "O usuário tem uma gata chamada Mel")]


def test_extracao_nula_e_ausencia_sao_descartadas():
    assert parse_facts("NULO") == []
    assert parse_facts("FATO: O nome do usuário não foi fornecido") == []


@pytest.mark.parametrize("resposta,esperado", [
    ("UPDATE 1", ("UPDATE", 11)), ("DELETE 2", ("DELETE", 22)), ('{"action": "DELETE", "n": 2}', ("DELETE", 22)),
    ("Resposta: DUPLICATE", ("DUPLICATE", None)), ("ADD", ("ADD", None)),
    ("UPDATE", ("ADD", None)),          # qual memória? sem número com 3 candidatas: nunca apaga no chute
    ("DELETE 7", ("ADD", None)), ("não sei", ("ADD", None)),
])
def test_decisao_do_classificador(resposta, esperado):
    d = parse_decision(resposta, CANDIDATOS)
    assert (d["action"], d["target_id"]) == esperado


def test_uma_candidata_sem_numero_e_a_propria():
    assert parse_decision("DELETE", CANDIDATOS[:1]) == {"action": "DELETE", "target_id": 11}


class _Store:
    def __init__(self, candidates):
        self.candidates, self.deleted, self.saved = candidates, [], []

    def search_candidates(self, _fact, threshold):
        return self.candidates

    def untagged(self):
        return []

    def delete_one(self, point_id):
        self.deleted.append(point_id)
        return True

    def upsert(self, fact, dedup_threshold=0.96, kind="fato"):
        self.saved.append((kind, fact))
        return True


def _worker_com(store, decisao, monkeypatch):
    monkeypatch.setattr(worker, "classify_relation", lambda *a, **k: decisao)
    w = worker.MemoryWorker.__new__(worker.MemoryWorker)
    w._store, w._on_store = store, None
    return w


def test_deixou_de_valer_apaga_a_memoria_e_nao_guarda_nada(monkeypatch):
    store = _Store(CANDIDATOS)
    _worker_com(store, {"action": "DELETE", "target_id": 22}, monkeypatch)._forget("O usuário vendeu o carro")
    assert store.deleted == [22] and store.saved == []


def test_mudanca_substitui_a_memoria(monkeypatch):
    store = _Store(CANDIDATOS)
    w = _worker_com(store, {"action": "UPDATE", "target_id": 11}, monkeypatch)
    assert w._smart_upsert("O usuário se mudou para Salvador", "fato")
    assert store.deleted == [11] and store.saved == [("fato", "O usuário se mudou para Salvador")]


def test_deixou_sem_nada_parecido_vira_fato(monkeypatch):
    store = _Store([])
    _worker_com(store, {"action": "ADD"}, monkeypatch)._forget("O usuário vendeu a moto")
    assert store.deleted == [] and store.saved == [("fato", "O usuário vendeu a moto")]


@pytest.fixture
def ltm(monkeypatch):
    import pidreams.memory.store as store_mod
    from tests.smoke.conftest import FakeEmbedModel
    from pidreams.memory.embedder import FastEmbedManager

    emb = FastEmbedManager.__new__(FastEmbedManager)
    emb.model_name, emb.model, emb._vector_size, emb._is_e5 = "fake", FakeEmbedModel(), None, False
    client = QdrantClient(location=":memory:")
    monkeypatch.setattr(store_mod, "QdrantClient", lambda **_kw: client)
    monkeypatch.setattr(store_mod, "FastEmbedManager", lambda *_a, **_kw: emb)
    return store_mod.LTMStore()


def test_perfil_so_com_memorias_de_perfil_e_no_maximo_10(ltm):
    ltm.upsert("O usuário mora em Cidade Exemplo")                     # antigas/fatos não entram
    for item in ("chá", "pão", "mar", "sol", "rio", "céu", "lua", "flor", "jazz", "rock", "xadrez", "ioga"):
        ltm.upsert(f"O usuário prefere {item}", dedup_threshold=1.0, kind="perfil")
    perfil = ltm.profile()
    assert len(perfil) == 10 and all("prefere" in p for p in perfil)


def test_busca_com_vetor_ja_calculado(ltm):
    ltm.upsert("O usuário gosta de café sem açúcar")
    vetor = ltm._embedder.embed_query("gosta de café")
    assert ltm.search("ignorado", score_min=0.1, query_vector=vetor) == ["O usuário gosta de café sem açúcar"]


def _agente_sem_modelo(monkeypatch, respostas):
    from pidreams.agent import llm as llm_mod

    agent = llm_mod.LLMAgent.__new__(llm_mod.LLMAgent)
    agent.history = [{"role": "system", "content": "sistema"}]
    agent._refresh_date = lambda: None
    agent._tools = agent._dispatch = None
    agent._camera_hint = lambda: ""

    class _Msg:
        def __init__(self, text):
            self.message = type("M", (), {"content": text, "tool_calls": None})()

    async def _call():
        return _Msg(respostas.pop(0))

    async def _stream():                    # the reply arrives as one chunk
        yield _Msg(respostas.pop(0))
    agent._call_llm = _call
    agent._stream_llm = _stream
    return agent


def test_documentos_e_perfil_nao_ficam_no_historico(monkeypatch):
    import asyncio

    agent = _agente_sem_modelo(monkeypatch, ["A multa é de 2%."])

    async def _run():
        return [s async for s in agent.chat_streaming("qual a multa?", recall=["O usuário mora em Recife"],
                                                       kb=["[contrato.pdf · p. 3] multa de 2%"], profile=["O usuário prefere respostas curtas"])]
    assert asyncio.run(_run()) == ["A multa é de 2%."]
    assert agent.history[1] == {"role": "user", "content": "qual a multa?"}


def test_historico_cortado_por_tamanho_em_turnos_inteiros(monkeypatch):
    from pidreams.core.config import CONFIG

    monkeypatch.setattr(CONFIG, "ollama_history_chars", 3000)
    agent = _agente_sem_modelo(monkeypatch, [])
    for i in range(5):
        agent.history += [{"role": "user", "content": f"pergunta {i}"}, {"role": "assistant", "content": "x" * 1000}]
    agent._trim_history()
    assert [m["content"] for m in agent.history if m["role"] == "user"] == ["pergunta 3", "pergunta 4"]
    assert agent.history[0]["role"] == "system"


def test_fechar_espera_a_reflexao_terminar(monkeypatch):
    import threading
    import time

    feito = []
    monkeypatch.setattr(worker.MemoryWorker, "_process", lambda self, turns: (time.sleep(0.3), feito.append(turns)))
    monkeypatch.setattr(worker.ollama, "Client", lambda **_kw: None)
    w = worker.MemoryWorker(_Store([]))
    w.submit([{"role": "user", "content": "tenho uma gata"}, {"role": "assistant", "content": "Legal!"}])
    assert w.drain(timeout=5) and len(feito) == 1
    assert threading.active_count() >= 1


def test_linha_que_nao_fala_do_usuario_e_descartada():
    raw = "FATO: O líder do projeto Aurora é Fulano Exemplo\nFATO: A usuária trabalha como enfermeira"
    assert parse_facts(raw) == [("fato", "A usuária trabalha como enfermeira")]
