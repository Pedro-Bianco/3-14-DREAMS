"""Grafo de memórias com o modelo real: assunto certo, tempo para montar e acomodar o
desenho e custo de um quadro na tela. Dados fictícios.

Uso: python -m tests.eval.memory_graph --model qwen2.5:14b
"""

import time

import numpy as np

from tests.eval._common import apply_model, arguments

MEMORIES = {
    "família": ["A filha do usuário se chama Bia", "A filha do usuário tem cinco anos", "O usuário é casado com a Carla Exemplo",
                "O irmão do usuário mora em Natal", "A mãe do usuário faz aniversário em maio", "O usuário tem dois sobrinhos",
                "O pai do usuário é aposentado", "A Bia estuda na escola Exemplo"],
    "trabalho": ["O usuário trabalha como engenheiro de dados", "O usuário trabalha na Empresa Exemplo há dois anos",
                 "O time do usuário se chama Time Azul", "O usuário tem reunião toda segunda às 9h",
                 "O chefe do usuário se chama Beltrano Exemplo", "O usuário usa Python no trabalho", "O usuário trabalha de casa às sextas"],
    "saúde/rotina": ["O usuário corre todas as manhãs no parque", "O usuário é vegetariano", "O usuário dorme às 23h",
                     "O usuário faz academia três vezes por semana", "O usuário toma café sem açúcar", "O usuário tem alergia a camarão",
                     "O usuário bebe dois litros de água por dia", "O usuário medita antes de dormir"],
    "lazer": ["O usuário está aprendendo violão", "O time de futebol do usuário é o Bahia", "O usuário gosta de filmes de ficção científica",
              "O usuário joga xadrez online", "O usuário tem uma gata chamada Mel", "O usuário gosta de surfar", "O usuário lê livros de fantasia"],
}
# "saúde/rotina" e "lazer" juntam assuntos vizinhos da lista; "a Bia estuda" pode ser estudos.
ACCEPT = {"família": {"família", "estudos"}, "trabalho": {"trabalho"}, "saúde/rotina": {"saúde", "rotina"},
          "lazer": {"lazer", "animais"}}


def _topics(client, model):
    from pidreams.core.config import CONFIG
    from pidreams.memory import topics

    texts = [t for v in MEMORIES.values() for t in v]
    expected = [k for k, v in MEMORIES.items() for _ in v]
    found, t = [], time.time()
    for start in range(0, len(texts), topics.BATCH):
        batch = texts[start:start + topics.BATCH]
        raw = client.chat(model=model, messages=[{"role": "user", "content": topics.prompt_for(batch)}],
                          options=CONFIG.ollama_options, think=False).message.content
        found += topics.parse_topics(raw, len(batch))
    ok = sum(f in ACCEPT[e] for f, e in zip(found, expected))
    for text, f, e in zip(texts, found, expected):
        if f not in ACCEPT[e]:
            print(f"FALHA [assunto] {text!r} → {f} (esperado {e})")
    print(f"assunto certo: {ok}/{len(texts)} ({100 * ok / len(texts):.0f}%) em {time.time() - t:.1f}s\n")


def _build_and_layout():
    from pidreams.memory.graph import Layout, build

    rng = np.random.default_rng(1)
    names = ("família", "trabalho", "saúde", "rotina", "lazer", "animais", "casa", "finanças")
    mems = [{"id": i, "text": f"Memória fictícia número {i}", "kind": "fato", "topic": names[i % 8],
             "ts": "2026-10-31", "vector": rng.normal(size=1024)} for i in range(300)]
    docs = [{"doc_id": "d1", "source": "contrato.pdf", "count": 400}, {"doc_id": "d2", "source": "manual.docx", "count": 30}]
    t = time.perf_counter()
    g = build(mems, docs)
    lay = Layout(g)
    lay.settle(100)
    first = time.perf_counter() - t
    steps = 100
    while not lay.settled:
        lay.step()
        steps += 1
    total = time.perf_counter() - t
    print(f"300 memórias + 2 documentos: {len(g.nodes)} pontos, {len(g.edges)} ligações")
    print(f"montar + 100 passos (desenho já legível): {first:.2f}s | acomodado em {steps} passos, {total:.2f}s")
    return g, lay


def _frame_cost(g, lay):
    import tkinter as tk

    from pidreams.ui.memory_graph import MemoryGraphView

    root = tk.Tk()
    root.geometry("900x700")
    view = MemoryGraphView(root)
    view.pack(fill=tk.BOTH, expand=True)
    root.update()
    view.show(g, lay)
    root.update()
    t, frames = time.perf_counter(), 30
    for _ in range(frames):
        lay.pos += np.random.default_rng(0).normal(size=lay.pos.shape)
        view.redraw()
        root.update()
    print(f"custo de um quadro na tela: {(time.perf_counter() - t) / frames * 1000:.1f} ms")
    root.destroy()


def main():
    import ollama

    from pidreams.core.config import CONFIG

    options = arguments(__doc__)
    model = apply_model(options.model)
    _topics(ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s), model)
    g, lay = _build_and_layout()
    _frame_cost(g, lay)


if __name__ == "__main__":
    main()
