"""Custo por quadro de cada aparência do painel central.

Desenha 150 quadros seguidos (sem o intervalo entre eles) parado e falando, numa janela
VISÍVEL, e mostra a fração de um núcleo que isso ocupa no intervalo da aparência. Meta:
≤ 15%. Com a janela oculta o Tk não pinta na tela e o custo dos desenhos vetoriais sai
até 6× menor que o real.
Uso: python -m tests.eval.appearance_cost [tamanhos, ex.: 300,600,900]
"""

import statistics
import sys
import time
import tkinter as tk

FRAMES = 150


def main():
    sys.stdout.reconfigure(encoding="utf-8")       # console do Windows em cp1252
    from pidreams.ui import appearances
    from pidreams.ui.appearances import base

    root_dir = tk.Tk()
    root_dir.geometry("+40+40")
    sizes = [int(s) for s in sys.argv[1].split(",")] if len(sys.argv) > 1 else [300]
    for id_, size in ((i, s) for i in appearances.CATALOG for s in sizes):
        a = appearances.create(id_, root_dir, size=size, bg="#010a14")
        a.pack()
        a.stop()
        root_dir.update()
        for state, volume in (("idle", 0.0), ("speaking", 0.15)):
            base._voice_level = lambda v=volume: v       # voz média medida (RMS ~0,12–0,22)
            a.set_state(state)
            times = []
            for _ in range(FRAMES):
                start_at = time.perf_counter()
                a._running = True
                a._loop()
                a._running = False
                root_dir.update()
                times.append(time.perf_counter() - start_at)
            median_val = statistics.median(times)
            p90 = sorted(times)[int(FRAMES * 0.9)]
            print(f"{id_:8s} {size:4d}px {state:9s} mediana {median_val * 1000:5.1f} ms  p90 {p90 * 1000:5.1f} ms  "
                  f"{median_val / (a.INTERVAL_MS / 1000) * 100:4.0f}% de um núcleo a {1000 / a.INTERVAL_MS:.0f} qps")
        a.destroy()
    root_dir.destroy()


if __name__ == "__main__":
    main()
