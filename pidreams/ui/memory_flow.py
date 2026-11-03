""""Como funciona" window of the Memória tab: how a memory is stored and how it is recalled.

A static flowchart on a Canvas: two columns of steps (storing, recalling) that meet in the local
database. The texts describe what agent/loop.py and memory/worker.py do; keep them in step.
"""

import tkinter as tk

from pidreams.ui import theme

_STORE = ("Quando você conta algo", theme.CYAN, [
    ("Você conversa",
     "Cada pergunta e resposta entra numa janela com as últimas 16 mensagens."),
    ("Hora de anotar",
     "A cada 4 mensagens, ou na hora quando você conta algo sobre si (\"eu moro em…\", \"vendi o carro\"). "
     "Roda em segundo plano e espera enquanto você aguarda uma resposta."),
    ("Extrair os fatos",
     "O modelo relê a janela e escreve frases curtas: PERFIL (nome, como chamar você, como responder), "
     "FATO (trabalho, família, rotina…) ou DEIXOU (o que não vale mais). Pedidos e comandos não viram memória."),
    ("Comparar com o que já sabe",
     "Cada fato é comparado com as memórias mais parecidas: novo → guarda; repetido → descarta; "
     "mudou → substitui a antiga; deixou de valer → apaga. Na dúvida, guarda."),
    ("Marcar o assunto",
     "Com o PI parado, o modelo marca o assunto de cada memória nova (família, trabalho, lazer…), "
     "que agrupa o mapa."),
])
_RECALL = ("Quando você pergunta", theme.VIOLET, [
    ("Você pergunta", "Por voz ou por texto."),
    ("Já respondeu hoje?",
     "Uma pergunta quase igual a outra feita hoje é respondida na hora, sem esperar o modelo."),
    ("Virar significado",
     "A pergunta vira um vetor de significado (modelo e5, no seu PC), calculado uma vez para a memória "
     "e para a Base."),
    ("Buscar",
     "Perfil: sempre. Fatos: os 3 mais parecidos. Base: até 5 trechos, por significado e pela palavra "
     "exata; \"e o prazo?\" leva junto a pergunta anterior."),
    ("Responder",
     "O que foi achado entra no contexto do modelo, que responde citando arquivo e página. "
     "O mapa marca com um anel amarelo o que foi usado."),
])
_DATABASE = ("Tudo fica no seu PC",
             "Memória e Base ficam num banco vetorial local (Qdrant), em %LOCALAPPDATA%\\PIDreams\\data. "
             "Nesta aba você adiciona, busca e apaga fatos. No Monitoramento e na Pesquisa profunda a "
             "memória não é usada.")


def show(master: tk.Misc) -> tk.Toplevel:
    window = tk.Toplevel(master, bg=theme.GLASS)
    window.title("Como a memória funciona")
    window.resizable(False, False)
    window.transient(master)

    p = theme.px
    col_w, gap, margin, pad = p(330), p(56), p(24), p(12)
    width = 2 * col_w + gap + 2 * margin
    canvas = tk.Canvas(window, bg=theme.GLASS, highlightthickness=0, width=width, height=p(100))
    canvas.pack()

    def box(x, y, w, title, text, color) -> tuple[int, int, int, int]:
        """Rounded-looking step box; returns its bounds."""
        t = canvas.create_text(x + pad, y + pad, text=title, anchor="nw", fill=color, font=theme.FONT_BOLD)
        top = canvas.bbox(t)[3] + p(4)
        d = canvas.create_text(x + pad, top, text=text, anchor="nw", fill=theme.TEXT2, font=theme.FONT_SMALL,
                               width=w - 2 * pad)
        bottom = canvas.bbox(d)[3] + pad
        rect = canvas.create_rectangle(x, y, x + w, bottom, fill=theme.GLASS_HI, outline=theme.BORDER)
        canvas.create_line(x + 1, y + 1, x + w - 1, y + 1, fill=color)          # accent on the top edge
        canvas.tag_lower(rect)
        return x, y, x + w, bottom

    def arrow(x0, y0, x1, y1, color, *middle):
        canvas.create_line(x0, y0, *middle, x1, y1, fill=color, width=p(2), arrow=tk.LAST,
                           arrowshape=(p(8), p(10), p(4)))

    def column(x, steps) -> list[tuple[int, int, int, int]]:
        title, color, items = steps
        canvas.create_text(x, margin, text=title.upper(), anchor="nw", fill=color, font=theme.FONT_SECTION)
        y, boxes = margin + p(30), []
        for i, (name, text) in enumerate(items):
            b = box(x, y, col_w, name, text, color)
            if boxes:
                arrow(x + col_w / 2, boxes[-1][3], x + col_w / 2, b[1], color)
            boxes.append(b)
            y = b[3] + p(22)
        return boxes

    left = column(margin, _STORE)
    right = column(margin + col_w + gap, _RECALL)
    top = max(left[-1][3], right[-1][3]) + p(30)
    db = box(margin, top, width - 2 * margin, *_DATABASE, theme.OK)

    # storing writes to the database; the search reads from it (elbow on the right edge)
    cx = margin + col_w / 2
    arrow(cx, left[-1][3], cx, db[1], theme.CYAN)
    canvas.create_text(cx + p(8), (left[-1][3] + db[1]) / 2, text="grava", anchor="w", fill=theme.MUTED,
                       font=theme.FONT_SMALL)
    search = right[3]
    edge = width - margin + p(12)
    arrow(db[2], db[1] + p(16), search[2], (search[1] + search[3]) / 2, theme.VIOLET,
          edge, db[1] + p(16), edge, (search[1] + search[3]) / 2)
    canvas.create_text(edge - p(4), db[1] - p(8), text="lê", anchor="se", fill=theme.MUTED, font=theme.FONT_SMALL)

    canvas.config(width=width + p(16), height=db[3] + margin)
    theme.button(window, "Fechar", window.destroy).pack(pady=(0, p(16)))
    window.bind("<Escape>", lambda _e: window.destroy())
    return window
