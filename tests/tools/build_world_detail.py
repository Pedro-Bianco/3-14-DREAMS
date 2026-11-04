"""Gera pidreams/assets/world_50m_outline.npy: litoral e fronteiras do Natural Earth 1:50m (domínio
público) em pontos a cada ~0,05° (~6 km), para o globo aproximado (aviões). Inteiros de 16 bits em
centésimos de grau (lon, lat): ~356 mil pontos, ~1,4 MB.

Uso: python -I tests/tools/build_world_detail.py caminho/ne_50m_admin_0_countries.geojson
O GeoJSON vem de https://github.com/nvkelso/natural-earth-vector (pasta geojson).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[2] / "pidreams" / "assets" / "world_50m_outline.npy"
STEP = 0.05


def main(path: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    points = []
    for feature in data["features"]:
        geometry = feature["geometry"]
        polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for ring in (poly[0] for poly in polys):
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                n = max(1, int(math.hypot(x2 - x1, y2 - y1) / STEP))
                t = np.arange(n) / n
                points.append(np.column_stack([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t]))
    lonlat = np.round(np.concatenate(points) * 100).astype(np.int16)
    lonlat = np.unique(lonlat, axis=0)                 # shared borders and repeated vertices only once
    np.save(OUT, lonlat)
    print(f"{OUT} — {len(lonlat):,} pontos, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1])
