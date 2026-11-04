"""Gera docs/memory-map.png: o mapa da memória com memórias e documentos FICTÍCIOS (nunca os reais).
Só a janela de teste.

Uso: python tests/tools/memory_map_docs.py [pasta de saída]
"""

import sys
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

from pidreams.memory import graph
from pidreams.memory.embedder import FastEmbedManager
from pidreams.ui import theme
from pidreams.ui.memory_graph import MemoryGraphView

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs"
W, H = 640, 480

MEMORIES = {
    "perfil": ["O nome do usuário é Fulano Exemplo", "O usuário quer ser chamado de Fulano",
               "O usuário prefere respostas curtas e diretas"],
    "família": ["O usuário é casado com Beltrana", "O usuário tem uma filha chamada Ana, de 6 anos",
                "A mãe do usuário mora em Cidade Exemplo", "O usuário tem um irmão mais novo chamado Caio",
                "A filha do usuário faz aniversário em 12 de março",
                "O usuário almoça com os pais aos domingos", "A esposa do usuário é professora",
                "A filha do usuário estuda na Escola Exemplo"],
    "trabalho": ["O usuário é engenheiro de dados", "O usuário trabalha na Empresa Exemplo desde 2019",
                 "O usuário trabalha em casa às segundas e sextas", "O usuário lidera uma equipe de 4 pessoas",
                 "O usuário está migrando o banco de dados da empresa para a nuvem",
                 "O usuário usa Python e SQL no trabalho", "O usuário tem reunião de equipe às terças",
                 "O chefe do usuário se chama Sicrano"],
    "lazer": ["O usuário toca violão", "O usuário gosta de ficção científica",
              "O usuário joga futebol às quintas", "O usuário está lendo Duna",
              "O usuário assiste séries de suspense", "O usuário gosta de cozinhar nos fins de semana",
              "O time do usuário é o Time Exemplo"],
    "animais": ["O usuário tem um cachorro chamado Biscoito", "Biscoito é um vira-lata de 3 anos",
                "O usuário tem uma gata chamada Pipoca"],
    "saúde": ["O usuário corre 5 km três vezes por semana", "O usuário é alérgico a camarão",
              "O usuário tem consulta no dentista todo semestre",
              "O usuário dorme por volta das 23h", "O usuário não toma café depois das 16h"],
    "estudos": ["O usuário está fazendo um curso de inglês", "O usuário quer aprender japonês",
                "O usuário terminou uma pós em ciência de dados em 2022"],
    "finanças": ["O usuário está juntando dinheiro para uma viagem ao Japão",
                 "O usuário paga o aluguel todo dia 5", "O usuário quer trocar de carro no ano que vem"],
}
DOCUMENTS = [("aluguel.pdf", ["p. 1", "p. 3", "p. 4"]), ("manual.pdf", []),
             ("Pesquisa - baterias.md", ["trecho 1", "trecho 2"])]
USED = {"profile": ["O nome do usuário é Fulano Exemplo"],
        "memories": ["O usuário tem um cachorro chamado Biscoito", "Biscoito é um vira-lata de 3 anos"],
        "pieces": []}

embedder = FastEmbedManager()
memories, n = [], 0
for topic, texts in MEMORIES.items():
    vectors = embedder.model.embed([f"passage: {t}" for t in texts])
    for text, vector in zip(texts, vectors):
        n += 1
        memories.append({"id": n, "text": text, "vector": vector,
                         "kind": "perfil" if topic == "perfil" else "fato", "topic": topic})
docs = [{"doc_id": f"doc{i}", "source": source, "count": 12} for i, (source, _) in enumerate(DOCUMENTS)]
pieces = [{"doc_id": f"doc{i}", "source": source, "where": where, "text": f"{source}, {where}"}
          for i, (source, wheres) in enumerate(DOCUMENTS) for where in wheres]

g = graph.build(memories, docs, pieces)
layout = graph.Layout(g)
layout.settle(600)

root = tk.Tk()
theme.init(root)
root.geometry(f"{W}x{H}+60+60")
view = MemoryGraphView(root)
view.pack(fill=tk.BOTH, expand=True)
root.update()
view.show(g, layout)
view.set_used(graph.used_nodes(g, USED))
for _ in range(80):
    root.update()
    root.after(30)
root.update()
x, y = view.winfo_rootx(), view.winfo_rooty()
path = OUT / "memory-map.png"
ImageGrab.grab(bbox=(x, y, x + view.winfo_width(), y + view.winfo_height())).save(path, optimize=True)
root.destroy()
print(f"{path} ({path.stat().st_size // 1024} KB)")
