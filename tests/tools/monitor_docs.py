"""Gera as imagens do Monitoramento para o README (só a janela de teste, dados públicos)."""
import math
import sys
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageGrab

from pidreams.ui import theme
from pidreams.ui.monitor_view import MonitorView

OUT = Path(sys.argv[1])


class Radio:
    station = None

    def play(self, s, wait_s=0):
        return None

    def stop(self):
        pass


root = tk.Tk()
theme.init(root)
root.geometry("640x600+40+40")
root.configure(bg=theme.BG)
v = MonitorView(root, on_close=root.destroy, on_ask=lambda q: None, radio=Radio())
v.pack(fill="both", expand=True)
root.update()
v.open()
v.globe.stop()                     # frames are driven here


def grab(widget=None):
    root.update()
    w = widget or root
    x, y = w.winfo_rootx(), w.winfo_rooty()
    return ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height()))


def wait_loaded():
    if v.globe.satellites is None or not v.globe.quakes or not v.globe.radios:
        root.after(300, wait_loaded)
        return
    root.after(200, gif)


def gif():
    g = v.globe
    g.lon0, g.lat0, g._spin, g._target = math.radians(-40), math.radians(12), False, None
    frames = []
    for _ in range(40):
        g.lon0 += math.radians(3.6)
        g.render()
        frames.append(grab(g).resize((360, 326), Image.LANCZOS).convert("P", palette=Image.ADAPTIVE, colors=48))
    frames[0].save(OUT / "monitor.gif", save_all=True, append_images=frames[1:], duration=70, loop=0, optimize=True)
    root.after(100, quake_shot)


def quake_shot():
    g = v.globe
    g.lon0, g.lat0, g.zoom = math.radians(150), math.radians(5), 1.25
    g.render()
    i = max(range(len(g.quakes)), key=lambda k: g.quakes[k]["mag"] if 100 < g.quakes[k]["lon"] < 180 or g.quakes[k]["lon"] < -170 else -1)
    g.render()
    v._picked("quake", i)
    g.selected = ("quake", i)
    g.render()
    grab().save(OUT / "monitor-terremotos.png")
    v._close_info()
    root.after(100, nav_shot)


def nav_shot():
    g = v.globe
    v._filter.set("Navegação")
    g.lon0, g.lat0, g.zoom = math.radians(-30), math.radians(20), 0.24
    g.render()
    grab().save(OUT / "monitor-navegacao.png")
    v._filter.set("Todos")
    root.after(100, radio_shot)


def radio_shot():
    g = v.globe
    v._layer_vars["radios"].set(True)
    v._layer_vars["satellites"].set(False)
    v._apply_layers()
    g.lon0, g.lat0, g.zoom = math.radians(10), math.radians(48), 2.4
    g.render()
    paris = min(range(len(g.radios)), key=lambda k: (g.radios[k]["lat"] - 48.85) ** 2 + (g.radios[k]["lon"] - 2.35) ** 2
                + (0 if "info" in g.radios[k]["name"].lower() else 5))
    v._picked("radio", paris)
    g.selected = ("radio", paris)
    v.radio_changed(g.radios[paris], None)
    g.render()
    grab().save(OUT / "monitor-radios.png")
    root.destroy()


root.after(500, wait_loaded)
root.mainloop()
print("ok")
