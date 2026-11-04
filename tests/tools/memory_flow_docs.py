"""Gera docs/memory-flow.png: a janela "Como funciona" da aba Memória (conteúdo fixo, sem dados
pessoais). Só a janela de teste.

Uso: python tests/tools/memory_flow_docs.py [pasta de saída]
"""

import sys
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

from pidreams.ui import memory_flow, theme

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs"

root = tk.Tk()
theme.init(root)
root.geometry("10x10+0+0")
window = memory_flow.show(root)
window.geometry("+40+20")
for _ in range(5):
    window.update()
    window.after(100)
window.lift()
window.update()
canvas = next(w for w in window.winfo_children() if isinstance(w, tk.Canvas))
x, y = canvas.winfo_rootx(), canvas.winfo_rooty()
path = OUT / "memory-flow.png"
ImageGrab.grab(bbox=(x, y, x + canvas.winfo_width(), y + canvas.winfo_height())).save(path, optimize=True)
root.destroy()
print(f"{path} ({path.stat().st_size // 1024} KB)")
