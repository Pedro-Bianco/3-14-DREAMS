"""Custo por quadro do globo com a camada de aviões no pior caso: 800 aviões com rastros cheios
(90 pontos), numa janela VISÍVEL. Meta: ≤ 50 ms por quadro (≥ 20 quadros/s ao arrastar).

Uso: python -m tests.eval.planes_cost
"""

import math
import statistics
import sys
import time
import tkinter as tk

import numpy as np

FRAMES = 60


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    from pidreams.monitor import planes
    from pidreams.ui import theme
    from pidreams.ui.globe import GlobeView

    root = tk.Tk()
    theme.init(root)
    root.geometry("1100x800+40+40")
    globe = GlobeView(root)
    globe.pack(fill=tk.BOTH, expand=True)
    root.update()
    globe.lat0, globe.lon0 = math.radians(40.6), math.radians(-73.8)        # New York, the busiest region measured
    globe.layers["planes"] = True
    globe.tracker = tracker = planes.Tracker()
    rng = np.random.default_rng(1)
    t0 = time.monotonic()
    tracker.update([{"hex": f"x{i}", "lat": 40.6 + rng.uniform(-4, 4), "lon": -73.8 + rng.uniform(-5, 5),
                     "speed_kt": rng.uniform(150, 480), "track": rng.uniform(0, 360), "fix_age_s": 0}
                    for i in range(800)], t0)
    for k in range(planes.TRAIL_MAX):                     # fill every trail (a few minutes "ahead" of the clock)
        tracker.positions(t0 + k * planes.TRAIL_EVERY_S / 10)
        tracker._trail_t = -1e9
    print(f"{len(tracker)} aviões, {len(tracker.trails()[0])} pontos de rastro")
    worst = 0.0
    for zoom in (1.0, 6.0, 12.0, 16.0):
        globe.zoom = zoom
        globe.render()
        root.update()
        times = []
        for _ in range(FRAMES):
            start = time.perf_counter()
            globe.render()
            root.update()
            times.append(time.perf_counter() - start)
        med, p90 = statistics.median(times) * 1000, statistics.quantiles(times, n=10)[-1] * 1000
        worst = max(worst, p90)
        print(f"zoom {zoom:4.0f}×: mediana {med:5.1f} ms  p90 {p90:5.1f} ms")
    root.destroy()
    print(f"pior p90: {worst:.1f} ms — meta ≤ 50 ms: {'OK' if worst <= 50 else 'ACIMA'}")


if __name__ == "__main__":
    main()
