"""Base de conhecimento com Qdrant local de verdade (pasta temporária) e embedder falso.

O embedder falso devolve o mesmo vetor para tudo: o significado empata e quem decide é a busca por
palavra — exatamente o caso dos códigos "2024-0815" × "2024-0816".
"""

import threading

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from pidreams.memory import kb_store
from pidreams.memory.kb_store import KBStore, label
from tests.fixtures.fake_documents import make_pdf, make_pptx


class _SameVector:
    vector_size = 4

    def embed_query(self, _q):
        return [0.5, 0.5, 0.5, 0.5]

    def embed_text(self, _t):
        return [0.5, 0.5, 0.5, 0.5]

    def embed_texts(self, texts, batch_size=32):
        return [[0.5, 0.5, 0.5, 0.5] for _ in texts]


@pytest.fixture
def base(tmp_path):
    store = KBStore(client=QdrantClient(path=str(tmp_path / "q")), embedder=_SameVector())
    assert store.available
    return store


def test_codigo_exato_vence_o_vizinho_e_rotulo_de_origem(base, tmp_path):
    pdf = make_pdf(tmp_path / "contrato.pdf", ["O contrato 2024-0816 trata da manutenção.",
                                               "Registrado sob o número 2024-0815, vigora por doze meses."])
    base.ingest_document(pdf)
    hits = base.search_hits("o que diz o contrato 2024-0815?", score_min=0)
    assert hits[0]["where"] == "p. 2" and label(hits[0]) == "contrato.pdf · p. 2"
    assert base.search("contrato 2024-0815", score_min=0)[0].startswith("[contrato.pdf · p. 2] Registrado")


def test_guardar_de_novo_substitui_e_remover_apaga_tudo(base, tmp_path):
    pptx = make_pptx(tmp_path / "apresentacao.pptx", [["Meta do trimestre"], ["Resultado de vendas"]])
    assert base.ingest_document(pptx) == 2
    assert base.ingest_document(pptx) == 2
    docs = base.list_documents()
    assert [(d["source"], d["kind"], d["count"]) for d in docs] == [("apresentacao.pptx", "pptx", 2)]
    base.delete_document(docs[0]["doc_id"])
    assert base.count() == 0 and base.search_hits("meta do trimestre", score_min=0) == []


def test_texto_colado_sem_posicao_e_substituido_pelo_mesmo_titulo(base):
    base.ingest("Primeira versão das regras da casa.", source_name="Regras")
    base.ingest("Segunda versão das regras da casa.", source_name="Regras")
    pieces = base.list_all()
    assert len(pieces) == 1 and pieces[0]["where"] == "" and "Segunda" in pieces[0]["text"]
    assert label(pieces[0]) == "Regras"


def test_cancelar_nao_deixa_documento_pela_metade(base, tmp_path):
    cancel = threading.Event()
    cancel.set()
    assert base.ingest_document(make_pdf(tmp_path / "longo.pdf", ["texto da página"] * 3), cancel=cancel) == 0
    assert base.count() == 0


def test_limiar_alto_nao_traz_nada(base):
    base.ingest("Receita de bolo de cenoura.", source_name="Receitas")
    assert base.search_hits("previsão do tempo amanhã", score_min=10) == []


def test_migra_a_colecao_antiga_e_apaga_depois(tmp_path):
    client = QdrantClient(path=str(tmp_path / "q"))
    client.create_collection(kb_store.KBStore._OLD_COLLECTION, vectors_config=VectorParams(size=4, distance=Distance.COSINE))
    client.upsert(kb_store.KBStore._OLD_COLLECTION, points=[
        PointStruct(id=1, vector=[0.5] * 4, payload={"text": "Regra um.", "source": "Regras"}),
        PointStruct(id=2, vector=[0.5] * 4, payload={"text": "Regra dois.", "source": "Regras"}),
        PointStruct(id=3, vector=[0.5] * 4, payload={"text": "Anotação solta.", "source": ""})])
    store = KBStore(client=client, embedder=_SameVector())
    names = {c.name for c in client.get_collections().collections}
    assert kb_store.KBStore._OLD_COLLECTION not in names
    assert sorted((d["source"], d["count"]) for d in store.list_documents()) == [("(sem título)", 1), ("Regras", 2)]


def _base_com_notas(scores):
    from types import SimpleNamespace

    store = KBStore.__new__(KBStore)
    store.available, store._embedder = True, _SameVector()
    points = [SimpleNamespace(score=s, payload={"source": f"doc{i}.pdf", "where": "p. 1", "text": f"trecho {i}"})
              for i, s in enumerate(scores)]
    # A normal base (100 pieces): the DBSF path, scores compared with the other candidates.
    store._client = SimpleNamespace(query_points=lambda *a, **k: SimpleNamespace(points=points),
                                    get_collection=lambda *_a: SimpleNamespace(points_count=100))
    return store


def test_casamento_fraco_manda_so_os_primeiros_trechos():
    assert len(_base_com_notas([1.40, 1.30, 1.20, 1.10, 1.00]).search_hits("oi")) == 2


def test_casamento_forte_manda_todos_e_abaixo_do_limite_nada():
    assert len(_base_com_notas([1.80, 1.30, 1.20, 1.10, 1.00]).search_hits("contrato")) == 5
    assert _base_com_notas([1.10, 1.00]).search_hits("oi") == []




def test_base_pequena_responde_pelas_palavras_do_assunto(base):
    """Visto em 2026-11-09: com um roteiro curto (2 trechos) a pergunta sobre ele nunca passava do limite."""
    base.ingest("Hospedagem: o hotel fica em Alfama. O check-in é a partir das 15h.", source_name="Roteiro")
    base.ingest("Passeios: Sintra no dia 15, trem saindo do Rossio às 9h.", source_name="Passeios")
    assert "check-in" in base.search_hits("Que horas é o check-in do hotel?")[0]["text"]
    assert "Sintra" in base.search_hits("Que horas sai o trem para Sintra?")[0]["text"]
    for unrelated in ("tudo bem?", "Qual é a capital da Austrália?", "Me conta uma piada"):
        assert base.search_hits(unrelated) == [], unrelated
