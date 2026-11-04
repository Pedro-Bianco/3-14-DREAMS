"""Memória de longo prazo com os modelos reais: extração, consolidação, consulta, latência e
orçamento de contexto. Dados fictícios; a consulta usa uma base Qdrant temporária.

Uso: python -m tests.eval.memory_extract --model qwen2.5:14b
"""

import statistics
import tempfile
import time

from tests.eval._common import apply_model, arguments

# ── extração: (conversa, [(categoria, trechos que precisam estar no fato)]; [] = nada) ──
U, A = "user", "assistant"
EXTRACTION = [
    ([(U, "me chamo Carla Exemplo e trabalho como enfermeira")], [("perfil", ["carla"]), ("fato", ["enfermeir"])]),
    ([(A, "Você ainda mora em Recife?"), (U, "sim, desde 2019")], [("fato", ["recife", "2019"])]),
    ([(U, "prefiro respostas curtas, sem enrolação")], [("perfil", ["curt"])]),
    ([(U, "a partir de agora me chama de chefe")], [("perfil", ["chefe"])]),
    ([(U, "minha filha se chama Bia e tem cinco anos")], [("fato", ["bia"])]),
    ([(U, "vendi o carro semana passada")], [("deixou", ["carro"])]),
    ([(U, "não trabalho mais na Acme, saí em setembro")], [("deixou", ["acme"])]),
    ([(A, "Qual é o seu time de futebol?"), (U, "Bahia, desde criança")], [("fato", ["bahia"])]),
    ([(U, "abre o spotify"), (A, "Abrindo o Spotify."), (U, "pausa a música")], []),
    ([(U, "qual a capital da Austrália?"), (A, "É Canberra.")], []),
    ([(U, "me lembra de pagar a conta amanhã"), (A, "Lembrete criado para amanhã.")], []),
    ([(U, "bom dia, tudo certo?")], []),
    # do teste no app: perguntas sobre documentos viravam "fatos"
    ([(U, "quanto pago se atrasar o aluguel?"), (A, "Pelo contrato_aluguel.pdf, a multa é de 2% e juros de 1% ao mês.")], []),
    ([(U, "quem é o líder do projeto Aurora?"), (A, "O líder do projeto Aurora é Fulano Exemplo, conforme a apresentacao.pptx.")], []),
    ([(U, "quanto foi o hotel na viagem?"), (A, "Pela planilha gastos.xlsx, o hotel foi R$ 900.")], []),
]

# ── consolidação: (memórias existentes, fato novo, ação esperada, índice esperado 1..3) ──
# Num "deixou de valer", UPDATE e DELETE no alvo certo apagam a memória antiga do mesmo jeito.
MEMS = ["O usuário mora em Recife", "O usuário tem um carro", "O usuário gosta de surfar"]
CLASSIFICATION = [
    (MEMS, "O usuário se mudou para Salvador", "UPDATE", 1),
    (MEMS, "O usuário vendeu o carro e não tem mais carro", "DELETE|UPDATE", 2),
    (MEMS, "O usuário curte surfe", "DUPLICATE", None),
    (MEMS, "O usuário tem uma gata chamada Mel", "ADD", None),
    (["O usuário trabalha na Acme", "O usuário mora em Recife", "O usuário tem 30 anos"],
     "O usuário não trabalha mais na Acme", "DELETE|UPDATE", 1),
    (["O usuário tem 30 anos", "O usuário gosta de café", "O usuário mora em Recife"],
     "O usuário agora tem 31 anos", "UPDATE", 1),
]

# ── consulta ──
MEMORIES = [("perfil", "O nome do usuário é Carla Exemplo"), ("perfil", "O usuário prefere respostas curtas"),
            ("perfil", "O usuário quer ser chamado de chefe"), ("fato", "O usuário mora em Recife desde 2019"),
            ("fato", "O usuário trabalha como enfermeira no Hospital Exemplo"),
            ("fato", "A filha do usuário se chama Bia e tem cinco anos"), ("fato", "O usuário é vegetariano"),
            ("fato", "O usuário tem uma gata chamada Mel"), ("fato", "O time do usuário é o Bahia"),
            ("fato", "O usuário está aprendendo violão"), ("fato", "O usuário corre todas as manhãs no parque")]
RELEVANT = [("me sugere uma receita para o jantar", "vegetariano"), ("como vai estar o tempo na minha cidade?", "recife"),
            ("que presente eu compro pra minha filha?", "bia"), ("teve jogo do meu time ontem?", "bahia"),
            ("me indica uma música para praticar", "violão"), ("o que eu dou de comer pra minha gata?", "mel"),
            ("qual o melhor horário para eu treinar amanhã?", "corre")]
UNRELATED = ["qual a capital da Austrália?", "abre a calculadora", "quanto é 15 vezes 4?",
             "me explica o que é fotossíntese", "pausa a música", "que horas são?"]


def _extraction(client, model):
    from pidreams.core.config import CONFIG
    from pidreams.memory.worker import _REFLECTION_PROMPT, format_chat, parse_facts

    ok_count = 0
    for conversation, expected in EXTRACTION:
        chat = format_chat([{"role": r, "content": c} for r, c in conversation])
        raw = client.chat(model=model, messages=[{"role": "user", "content": _REFLECTION_PROMPT.format(chat=chat)}],
                          options=CONFIG.ollama_options, think=False).message.content
        facts = parse_facts(raw)
        if not expected:
            ok = not facts
        else:
            ok = all(any(k == kind and all(w in f.lower() for w in words) for k, f in facts)
                     for kind, words in expected)
        ok_count += ok
        print(f"{'OK   ' if ok else 'FALHA'} [extrair] {conversation[-1][1]!r} → {facts}")
    print(f"extração: {ok_count}/{len(EXTRACTION)} ({100 * ok_count / len(EXTRACTION):.0f}%)\n")


def _classification(model):
    from pidreams.core.config import CONFIG
    from pidreams.memory.updater import classify_relation

    ok_count = 0
    for mems, new, action, index in CLASSIFICATION:
        candidates = [{"id": 100 + i, "text": m, "score": 0.8} for i, m in enumerate(mems, 1)]
        d = classify_relation(candidates, new, CONFIG.ollama_host, model)
        ok = d["action"] in action.split("|") and (index is None or d["target_id"] == 100 + index)
        ok_count += ok
        print(f"{'OK   ' if ok else 'FALHA'} [consolidar] {new!r} → {d['action']} {d['target_id']} (esperado {action} {index})")
    print(f"consolidação: {ok_count}/{len(CLASSIFICATION)} ({100 * ok_count / len(CLASSIFICATION):.0f}%)\n")


def _retrieval_and_latency():
    import pidreams.memory.store as store_mod
    from qdrant_client import QdrantClient

    from pidreams.core.config import CONFIG

    folder = tempfile.mkdtemp()
    real_client = QdrantClient(path=folder)
    original = store_mod.QdrantClient
    store_mod.QdrantClient = lambda **_kw: real_client
    try:
        store = store_mod.LTMStore()
    finally:
        store_mod.QdrantClient = original
    for kind, text in MEMORIES:
        store.upsert(text, dedup_threshold=1.0, kind=kind)

    timings = {"vetor da pergunta": [], "busca": [], "perfil": []}
    positives, negatives, hits = [], [], 0
    for question, word in RELEVANT:
        t = time.perf_counter(); vec = store._embedder.embed_query(question); timings["vetor da pergunta"].append(time.perf_counter() - t)
        t = time.perf_counter(); results = store._query_points(vec, CONFIG.ltm_top_k, 0.0, with_filter=True); timings["busca"].append(time.perf_counter() - t)
        t = time.perf_counter(); store.profile(); timings["perfil"].append(time.perf_counter() - t)
        right = [r.score for r in results if word in r.payload["text"].lower()]
        hits += bool(right)
        positives.append(right[0] if right else 0.0)
        print(f"{'OK   ' if right else 'FALHA'} [consulta] {question!r} → {[(round(r.score, 3), r.payload['text'][:40]) for r in results]}")
    for question in UNRELATED:
        vec = store._embedder.embed_query(question)
        results = store._query_points(vec, 1, 0.0, with_filter=True)
        negatives.append(results[0].score if results else 0.0)
    print(f"\nconsulta: memória certa no top {CONFIG.ltm_top_k} em {hits}/{len(RELEVANT)}")
    print(f"nota da memória certa: min {min(positives):.3f} mediana {statistics.median(positives):.3f}")
    print(f"melhor nota sem relação: max {max(negatives):.3f} mediana {statistics.median(negatives):.3f}")
    print(f"limiar sugerido (meio do vão): {(min(p for p in positives if p) + max(negatives)) / 2:.3f} | atual {CONFIG.ltm_score_min}")
    print("latência por turno (mediana): " + ", ".join(f"{k} {statistics.median(v) * 1000:.0f} ms" for k, v in timings.items()) + "\n")


def _context_budget(client, model):
    """Worst realistic turn, after the history trim: long past answers, a web result, profile,
    memories, 5 document pieces and all tools."""
    from pidreams.agent import tools
    from pidreams.agent.llm import LLMAgent
    from pidreams.core.config import CONFIG

    agent = LLMAgent()
    for i in range(CONFIG.ollama_history_turns + 2):
        agent.history.append({"role": "user", "content": f"Pergunta de teste número {i} sobre um assunto qualquer do dia a dia."})
        if i % 4 == 3:
            agent.history.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "pesquisar_web", "arguments": {"consulta": "x"}}}]})
            agent.history.append({"role": "tool", "content": ("Resultado de pesquisa com título, trecho e endereço. " * 80)[:3500]})
        agent.history.append({"role": "assistant", "content": ("Resposta longa explicando o assunto com calma e detalhes. " * 30)[:1500]})
    agent._trim_history()
    piece = "Trecho de documento fictício com cláusulas, valores e prazos para encher a parte. " * 12
    kb = [f"[contrato.pdf · p. {i}] {piece}" for i in range(1, CONFIG.kb_top_k + 1)]
    content = agent._build_user_content("Qual a multa por atraso no contrato?", [m for _, m in MEMORIES[3:6]], kb,
                                        [m for k, m in MEMORIES if k == "perfil"])
    messages = agent.history + [{"role": "user", "content": content}]
    r = client.chat(model=model, messages=messages, tools=tools.active_tool_schemas(),
                    options={**CONFIG.ollama_options, "num_predict": 1}, think=False)
    total = r.prompt_eval_count + CONFIG.ollama_num_predict
    print(f"contexto no pior caso: prompt {r.prompt_eval_count} tokens + resposta até {CONFIG.ollama_num_predict} "
          f"= {total} de {CONFIG.ollama_num_ctx} ({100 * total / CONFIG.ollama_num_ctx:.0f}%), "
          f"{sum(m['role'] == 'user' for m in agent.history)} turnos no histórico")


def main():
    import ollama

    from pidreams.core.config import CONFIG

    options = arguments(__doc__)
    model = apply_model(options.model)
    client = ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)
    start = time.time()
    _extraction(client, model)
    _classification(model)
    _retrieval_and_latency()
    _context_budget(client, model)
    print(f"\nmemória [{model}] em {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
