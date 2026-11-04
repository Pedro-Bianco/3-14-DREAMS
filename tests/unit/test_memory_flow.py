"""Janela "Como funciona" da aba Memória: abre, mostra as duas colunas e fecha."""

import tkinter as tk

from pidreams.ui import memory_flow, theme


def test_mostra_o_fluxo_e_fecha():
    root = tk.Tk()
    root.withdraw()
    theme.init(root)
    try:
        window = memory_flow.show(root)
        window.update()
        canvas = next(w for w in window.winfo_children() if isinstance(w, tk.Canvas))
        texts = " ".join(canvas.itemcget(i, "text") for i in canvas.find_all() if canvas.type(i) == "text")
        assert "QUANDO VOCÊ CONTA ALGO" in texts and "QUANDO VOCÊ PERGUNTA" in texts
        assert "Tudo fica no seu PC" in texts
        next(w for w in window.winfo_children() if isinstance(w, tk.Button)).invoke()   # Fechar
        assert not window.winfo_exists()
    finally:
        root.destroy()
