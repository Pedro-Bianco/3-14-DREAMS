"""Base de documentos com os modelos reais: busca (top 3), notas para o limiar e citação na resposta.

Documentos fictícios gerados aqui (PDF, Word, slides, planilha, CSV, texto) numa base Qdrant
temporária — a base real não é tocada.
Uso: python -m tests.eval.documents --model qwen2.5:14b
"""

import asyncio
import re
import statistics
import tempfile
import time
from pathlib import Path

from tests.eval._common import apply_model, arguments
from tests.fixtures.fake_documents import make_docx, make_pdf, make_pptx, make_xlsx

PDF_PAGES = [
    "Contrato de prestação de serviços entre a Empresa Exemplo e o Cliente Fictício.",
    "O presente contrato, registrado sob o número 2024-0815, vigora por doze meses a partir da assinatura.",
    "O contrato 2024-0816, anexo, trata apenas da manutenção dos equipamentos do escritório.",
    "Em caso de atraso no pagamento incidirá penalidade por mora de 2% ao mês sobre o valor devido.",
    "A rescisão antecipada exige aviso prévio por escrito com trinta dias de antecedência.",
    "O foro eleito para resolver qualquer disputa é o da comarca de Cidade Exemplo.",
]
DOCX = ["Manual do ar-condicionado Modelo X200.",
        "Para trocar o filtro, desligue o aparelho, remova a tampa frontal e puxe o filtro para cima.",
        "Limpe o filtro a cada trinta dias com água corrente e sabão neutro.",
        "O código de erro E7 indica falha no sensor de temperatura; chame a assistência."]
PPTX = [["Planejamento 2026"], ["Meta do trimestre", "Aumentar a satisfação dos clientes em 10 pontos"],
        ["Orçamento", "O orçamento de marketing do ano é de 48 mil reais"], ["Próximos passos", "Contratar dois analistas até junho"]]
XLSX = {"Vendas": [["Região", "Mês", "Vendas", "Responsável"], ["Sul", "março", "1520", "Ana Exemplo"],
                   ["Norte", "março", "980", "Bruno Teste"], ["Sul", "abril", "1710", "Ana Exemplo"]],
        "Estoque": [["Produto", "Código", "Quantidade"], ["Parafuso", "PX-9931", "4000"], ["Porca", "PX-9932", "2500"]]}

# (pergunta, arquivo esperado, trecho do rótulo esperado, é código exato?)
QUESTIONS = [
    ("Qual a multa por atraso no pagamento?", "contrato.pdf", "p. 4", False),
    ("O que diz o contrato 2024-0815?", "contrato.pdf", "p. 2", True),
    ("Por quanto tempo o contrato vale?", "contrato.pdf", "p. 2", False),
    ("Com quanto tempo de antecedência preciso avisar para cancelar o contrato?", "contrato.pdf", "p. 5", False),
    ("Onde serão resolvidas as brigas judiciais do contrato?", "contrato.pdf", "p. 6", False),
    ("Como eu troco o filtro do ar-condicionado?", "manual.docx", "trecho", False),
    ("O que significa o erro E7?", "manual.docx", "trecho", True),
    ("Qual é a meta do trimestre?", "planejamento.pptx", "slide 2", False),
    ("Quanto temos de verba para marketing?", "planejamento.pptx", "slide 3", False),
    ("Quanto a região Sul vendeu em março?", "planilha.xlsx", "aba Vendas", False),
    ("Quantas unidades do código PX-9932 temos?", "planilha.xlsx", "aba Estoque", True),
    ("Em que cidade mora o cliente Carlos Teste?", "clientes.csv", "linha", False),
    ("Qual o telefone de emergência do condomínio?", "notas.txt", "", False),
    # falados como no teste do app (frase longa, verbo em vez do substantivo)
    ("Eu quero que você me fale quanto eu pago se eu atrasar o pagamento.", "contrato.pdf", "p. 4", False),
    ("Quem é a responsável pelas vendas da região Sul?", "planilha.xlsx", "aba Vendas", False),
]
UNRELATED = ["Qual a capital da Austrália?", "Me conta uma piada.", "Como está o tempo amanhã?",
             "Quem ganhou a Copa de 2002?", "Abre a calculadora.", "Que horas são?"]


def _build(folder: Path):
    make_pdf(folder / "contrato.pdf", PDF_PAGES)
    make_docx(folder / "manual.docx", DOCX)
    make_pptx(folder / "planejamento.pptx", PPTX)
    make_xlsx(folder / "planilha.xlsx", XLSX)
    (folder / "clientes.csv").write_text("Nome;Cidade;Plano\nCarlos Teste;Salvador;Ouro\nDébora Exemplo;Belém;Prata\n",
                                         encoding="utf-8")
    (folder / "notas.txt").write_text("Telefone de emergência do condomínio: 0800 000 1234. Síndico: Sr. Fictício.",
                                      encoding="utf-8")
    return sorted(folder.iterdir())


def main():
    options = arguments(__doc__)
    model = apply_model(options.model)
    from qdrant_client import QdrantClient

    from pidreams.core.config import CONFIG
    from pidreams.memory.embedder import FastEmbedManager
    from pidreams.memory.kb_store import KBStore, label

    folder = Path(tempfile.mkdtemp())
    store = KBStore(client=QdrantClient(path=str(folder / "qdrant")),
                    embedder=FastEmbedManager(CONFIG.ltm_embedding_model))
    t = time.time()
    for f in _build(folder / "docs" if (folder / "docs").mkdir() is None else folder):
        store.ingest_document(f)
    print(f"guardados {len(store.list_documents())} documentos, {store.count()} partes em {time.time() - t:.0f}s\n")

    # ── busca: top 3 e notas ──
    hits_ok = codes_ok = codes = 0
    positive_scores, negative_scores = [], []
    for question, file, where, exact in QUESTIONS:
        hits = store.search_hits(question, score_min=0)[:3]
        ok = any(h["source"] == file and where in h["where"] for h in hits)
        hits_ok += ok
        codes += exact
        codes_ok += ok and exact
        best = next((h["score"] for h in hits if h["source"] == file and where in h["where"]), None)
        if best is not None:
            positive_scores.append(best)
        print(f"{'OK   ' if ok else 'FALHA'} {question} → {[label(h) for h in hits]}")
    for question in UNRELATED:
        hits = store.search_hits(question, score_min=0)[:1]
        negative_scores.append(hits[0]["score"] if hits else 0.0)
    print(f"\nbusca: {hits_ok}/{len(QUESTIONS)} no top 3 ({100 * hits_ok / len(QUESTIONS):.0f}%), códigos {codes_ok}/{codes}")
    print(f"notas do trecho certo: min {min(positive_scores):.3f} mediana {statistics.median(positive_scores):.3f}")
    print(f"melhor nota sem relação: max {max(negative_scores):.3f} mediana {statistics.median(negative_scores):.3f}")
    opens = sum(store.search_hits(q) != [] for q, *_ in QUESTIONS)
    leaks = sum(store.search_hits(q) != [] for q in UNRELATED)
    print(f"porta (melhor trecho >= {CONFIG.kb_score_min}): abre em {opens}/{len(QUESTIONS)} perguntas sobre "
          f"documentos e em {leaks}/{len(UNRELATED)} sem relação\n")

    # ── citação com o modelo de conversa ──
    from pidreams.agent import llm as llm_module

    async def answer(question, score_min=None):
        llm_module.dispatch_tool = lambda name, args: "[resultado fictício]"
        agent = llm_module.LLMAgent()
        kb = store.search(question, score_min=score_min)
        return kb, " ".join([f async for f in agent.chat_streaming(question, kb=kb)])

    cited = invented = 0
    for question, file, where, _ in QUESTIONS:
        kb, reply = asyncio.run(answer(question))
        ok = Path(file).stem.lower() in reply.lower()
        cited += ok
        print(f"{'OK   ' if ok else 'FALHA'} [citação] {question} → {reply[:110]!r}")
    for question in UNRELATED:
        kb, reply = asyncio.run(answer(question, score_min=0))   # pior caso: a porta abriu sem motivo
        bad = bool(re.search(r"\.(pdf|docx|pptx|xlsx|csv|txt)\b", reply.lower()))
        invented += bad
        print(f"{'FALHA' if bad else 'OK   '} [sem documento] {question} → {len(kb)} partes; {reply[:90]!r}")
    print(f"\ndocumentos [{model}]: citação {cited}/{len(QUESTIONS)} ({100 * cited / len(QUESTIONS):.0f}%), "
          f"citações inventadas {invented}")


if __name__ == "__main__":
    main()
