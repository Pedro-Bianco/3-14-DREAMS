"""Pesquisa profunda: fontes (respostas gravadas fictícias), etapas com modelo falso,
citações só de fontes lidas, cancelamento, frases e relatório guardado sem sobrescrever."""

import json
import threading
import time

import pytest

from pidreams.research import agent, job, sources


# ── fontes ──

def test_wikipedia_429_espera_e_tenta_de_novo(monkeypatch):
    import io
    import urllib.error
    calls = []

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=15):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return Resp(b'{"query": {"pages": {"7": {"title": "Artigo", "index": 1, "extract": "Resumo do artigo."}}}}')
    monkeypatch.setattr(sources.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sources, "_WIKI_GAP_S", 0)
    assert [h["title"] for h in sources.wiki_search("tema")] == ["Artigo"] and len(calls) == 2


def test_trecho_util_fica_com_o_inicio_e_os_paragrafos_do_assunto():
    text = "Introdução.\n" + "\n".join(f"Parágrafo {i} sobre outra coisa." for i in range(400)) + "\nO custo das baterias caiu."
    part = sources.useful_part(text, ["custo das baterias"], limit=300)
    assert part.startswith("Introdução.") and "custo das baterias caiu" in part and len(part) <= 300


# ── etapas ──

def test_plano_le_as_perguntas_e_cai_no_tema_sem_formato():
    plan = job.parse_plan("P: Como funciona? | como funciona bateria | how battery works\nlixo\n2. P: Quanto custa? | custo", "tema")
    assert [p["question"] for p in plan] == ["Como funciona?", "Quanto custa?"] and plan[1]["en"] == ""
    assert job.parse_plan("sem formato", "Tema X") == [{"question": "Tema X", "pt": "Tema X", "en": ""}]


def test_palavra_chave_do_plano():
    assert job.parse_keyword("C: Pix\nP: Origem | origem | origin", "a história do Pix") == "Pix"
    assert job.parse_keyword("P: só pergunta", "tema longo") == "tema longo"


def test_citacao_inexistente_e_removida():
    assert job.clean_citations("Fato [1][7]. Outro [2].", {1, 2}) == "Fato [1]. Outro [2]."


def _fake_sources(monkeypatch, fail_urls=()):
    monkeypatch.setattr(sources, "wiki_search", lambda q, lang="pt", limit=2: [
        {"title": f"Artigo {lang} {q}", "lang": lang, "origin": f"wikipedia-{lang}", "url": f"https://{lang}.exemplo/{q}"}])
    monkeypatch.setattr(sources, "news", lambda q: [])

    def wiki_text(title, lang="pt"):
        if any(u in title for u in fail_urls):
            raise OSError("não abriu")
        return "Texto fictício com fatos sobre o tema. " * 20
    monkeypatch.setattr(sources, "wiki_text", wiki_text)


def _fake_chat(prompt, max_tokens, cancel, strong=False):
    if prompt.startswith("Tema de pesquisa"):
        return "P: Pergunta um | busca um | search one\nP: Pergunta dois | busca dois | search two"
    if "Anote" in prompt:
        return "- fato fictício importante tirado do texto"
    if prompt.startswith("Tema:"):
        return "## Resumo\nResumo com fato [1] e número inventado [9].\n## Conclusão\nFim [2]."
    return "Resumo falado de teste."


def _run(j):
    j.run()
    return j


def test_pesquisa_completa_cita_so_o_que_leu(monkeypatch):
    _fake_sources(monkeypatch, fail_urls=("busca dois",))
    saved, said = [], []
    j = _run(job.ResearchJob("tema fictício", _fake_chat, announce=said.append,
                             save=lambda t, r: saved.append((t, r)) or ("nome", None)))
    assert j.state == "pronta" and saved
    report = saved[0][1]
    assert "[9]" not in report and "[1]" in report
    listed = [l for l in report.splitlines() if l.startswith("[")]
    assert all("busca dois" not in l for l in listed)          # the one that failed is not a source
    assert said[0].startswith("Vou pesquisar 2 perguntas") and said[-1] == "Resumo falado de teste."


def test_sem_material_avisa_sem_inventar_relatorio(monkeypatch):
    _fake_sources(monkeypatch)
    j = _run(job.ResearchJob("tema", lambda p, m, c, **_k: "NADA" if "Anote" in p else _fake_chat(p, m, c)))
    assert j.report == "" and "Não encontrei material suficiente" in j.summary


def test_cancelar_para_em_poucos_segundos(monkeypatch):
    _fake_sources(monkeypatch)

    def slow_chat(prompt, max_tokens, cancel, strong=False):
        for _ in range(100):                                  # a long reply, streamed
            if cancel.is_set():
                raise job.Cancelled()
            time.sleep(0.05)
        return _fake_chat(prompt, max_tokens, cancel)
    states = []
    j = job.ResearchJob("tema", slow_chat, on_progress=lambda s: states.append(s["etapa"]))
    j.start()
    time.sleep(0.3)
    t = time.time()
    j.cancel.set()
    j._thread.join(5)
    assert not j.running and time.time() - t < 5 and states[-1] == "cancelada" and j.report == ""


# ── agente e frases ──

def test_frases_decididas_pelo_codigo():
    assert agent.is_open_request("Abra a pesquisa profunda.") and not agent.is_open_request("abra o spotify")
    assert agent.is_close_request("fechar pesquisa") and agent.is_cancel_request("Cancelar pesquisa!")


def test_uma_pesquisa_por_vez(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_chat(prompt, max_tokens, cancel):
        started.set()
        release.wait(5)
        raise job.Cancelled()
    tools = agent.ResearchAgentTools(lambda *_: None, chat_fn=blocking_chat)
    assert tools.dispatch("pesquisar", {"tema": "A"}).startswith("Comecei")
    started.wait(2)
    assert tools.dispatch("pesquisar", {"tema": "B"}).startswith("Já há uma pesquisa")
    assert "veio sem tema" in tools.dispatch("pesquisar", {})
    tools.cancel()
    release.set()


def test_relatorio_guardado_com_data_e_sem_sobrescrever(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.paths, "user_data_dir", lambda: tmp_path)
    ingested = []

    class Base:
        available = True

        def ingest(self, text, name):
            ingested.append(name)
    n1, f1 = agent.save_report(Base(), "baterias", "# Relatório 1")
    time.sleep(1.1)
    n2, f2 = agent.save_report(Base(), "baterias", "# Relatório 2")
    assert n1 != n2 and n1.startswith("Pesquisa: baterias — ") and f1 != f2 and f1.exists() and f2.exists()
    assert ingested == [n1, n2]


# ── perguntas de esclarecimento ──

def test_perguntas_de_opcao_e_tema_claro():
    raw = "Q: Qual o foco? | Conceitos | Prática | Comparação\nQ: só uma opção | A\nlixo\nQ: Profundidade? | Geral | Detalhada"
    assert job.parse_clarify(raw) == [{"question": "Qual o foco?", "options": ["Conceitos", "Prática", "Comparação"]},
                                      {"question": "Profundidade?", "options": ["Geral", "Detalhada"]}]
    assert job.parse_clarify("NADA") == []


def test_escolhas_esperam_a_resposta_e_entram_no_plano(monkeypatch):
    _fake_sources(monkeypatch)
    prompts = []

    def chat(prompt, max_tokens, cancel, strong=False):
        prompts.append(prompt)
        if "múltipla escolha" in prompt:
            return "Q: Qual o foco? | Conceitos | Prática"
        return _fake_chat(prompt, max_tokens, cancel)
    seen = []
    j = job.ResearchJob("tema vago", chat, on_progress=lambda s: seen.append(s), save=lambda t, r: ("n", None))
    j.start()
    for _ in range(50):
        if j.awaiting:
            break
        time.sleep(0.05)
    assert j.awaiting and any(s["escolhas"] for s in seen)
    j.answer(["Prática"])
    j._thread.join(5)
    plan = next(p for p in prompts if p.startswith("Tema de pesquisa: "))
    assert "O que o usuário quer: Qual o foco? Prática" in plan and j.state == "pronta"


def test_resposta_falada_as_opcoes():
    choices = [{"question": "Foco?", "options": ["Conceitos", "Aplicação prática"]},
               {"question": "Profundidade?", "options": ["Visão geral", "Detalhada"]}]
    assert agent.match_choices(choices, "a segunda e detalhada") == ["Aplicação prática", "Detalhada"]
    assert agent.match_choices(choices, "a primeira") == ["Conceitos", ""]
    assert agent.match_choices(choices, "tanto faz") == ["", ""]
    assert agent.match_choices(choices[:1], "quero algo para iniciantes") == ["quero algo para iniciantes"]


def test_free_wording_opens_and_closes_the_research_mode():
    from pidreams.research import agent

    assert agent.is_open_request("Vamos abrir a pesquisa profunda?")
    assert agent.is_close_request("sair do modo de pesquisa")
    assert not agent.is_open_request("o que a pesquisa profunda faz?")
    assert not agent.is_close_request("abre a pesquisa profunda")
