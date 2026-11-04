"""Gera pidreams/assets/world_110m.json a partir do Natural Earth 1:110m (domínio público).

Uso: python -m tests.tools.build_world caminho/ne_110m_admin_0_countries.geojson
O GeoJSON vem de https://github.com/nvkelso/natural-earth-vector (pasta geojson).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[2] / "pidreams" / "assets" / "world_110m.json"
STEP_BORDER = 0.6     # degrees between border points
STEP_LAND = 1.25      # degrees between land dots (north-south)


def rings_of(geometry):
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [ring for poly in polys for ring in poly[:1]]     # outer rings only (holes are tiny at 1:110m)


def inside(lon, lat, ring):
    x, y = np.asarray(ring)[:, 0], np.asarray(ring)[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    hit = ((y > lat[:, None]) != (y2 > lat[:, None])) & \
          (lon[:, None] < (x2 - x) * (lat[:, None] - y) / (y2 - y + 1e-12) + x)
    return hit.sum(axis=1) % 2 == 1


def main(path):
    features = json.load(open(path, encoding="utf-8"))["features"]
    countries, border = [], []
    for f in features:
        p = f["properties"]
        rings = [[[round(x, 2), round(y, 2)] for x, y in r] for r in rings_of(f["geometry"])]
        countries.append({"name": p.get("NAME_PT") or p["NAME"], "iso": p.get("ISO_A2_EH") or p.get("ISO_A2"), "rings": rings})
        for r in rings:
            for (x1, y1), (x2, y2) in zip(r, r[1:]):
                n = max(1, int(math.hypot(x2 - x1, y2 - y1) / STEP_BORDER))
                border += [[round(x1 + (x2 - x1) * k / n, 2), round(y1 + (y2 - y1) * k / n, 2)] for k in range(n)]
    land = []
    for lat in np.arange(-85, 85, STEP_LAND):
        step = STEP_LAND / max(0.15, math.cos(math.radians(lat)))       # even spacing on the sphere
        lons = np.arange(-180, 180, step)
        lats = np.full_like(lons, lat)
        found = np.zeros(len(lons), bool)
        for c in countries:
            for r in c["rings"]:
                a = np.asarray(r)
                if a[:, 1].min() <= lat <= a[:, 1].max():
                    box = (lons >= a[:, 0].min()) & (lons <= a[:, 0].max()) & ~found
                    if box.any():
                        found[np.where(box)[0][inside(lons[box], lats[box], r)]] = True
        land += [[round(float(x), 2), round(float(lat), 2)] for x in lons[found]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "Natural Earth 1:110m admin 0 countries (public domain)",
                               "countries": countries, "border": border, "land": land},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(countries)} países, {len(border)} pontos de fronteira, {len(land)} pontos de terra → "
          f"{OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
