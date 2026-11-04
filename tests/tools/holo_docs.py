"""Gera docs/face.gif e docs/brain.gif: as aparências em holograma seguindo um ponteiro simulado,
ouvindo, pensando e falando (voz simulada). Só a janela de teste.

Uso: python tests/tools/holo_docs.py [pasta de saída]
"""

import math
import sys
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageGrab

from pidreams.ui import theme
from pidreams.ui.appearances.brain import BrainCanvas
from pidreams.ui.appearances.face import FaceCanvas

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs"
SIZE, FRAMES = 300, 60


def state_at(i: int) -> str:
    return "listening" if i < 15 else "thinking" if i < 25 else "speaking" if i < 50 else "idle"


def record(cls, name: str) -> None:
    root = tk.Tk()
    theme.init(root)
    root.configure(bg=theme.GLASS)
    root.geometry("+60+60")
    a = cls(root, size=SIZE, bg=theme.GLASS)
    a.pack()
    a.stop()
    root.update()
    frames = []
    for i in range(FRAMES):
        angle = i / FRAMES * math.tau                          # the pointer circles around
        cx, cy = a.winfo_rootx() + SIZE / 2, a.winfo_rooty() + SIZE / 2
        a.winfo_pointerxy = lambda: (cx + 520 * math.cos(angle), cy + 260 * math.sin(angle))
        a._t = 1.0 + i * 0.12
        a.state = state_at(i)
        a.voice = abs(math.sin(i * 0.9)) * 0.9 if a.state == "speaking" else 0.0
        a._frame_holder()
        root.update()
        x, y = a.winfo_rootx(), a.winfo_rooty()
        shot = ImageGrab.grab(bbox=(x, y, x + SIZE, y + SIZE))      # same size as core.gif and orb.gif, no resize: it would fade the thin dots
        frames.append(shot.convert("P", palette=Image.ADAPTIVE, colors=64))
    root.destroy()
    path = OUT / name
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0, optimize=True)
    print(f"{path} ({path.stat().st_size // 1024} KB)")


record(FaceCanvas, "face.gif")
record(BrainCanvas, "brain.gif")
