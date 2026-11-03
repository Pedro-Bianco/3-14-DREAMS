"""Countries, borders and land dots of the globe (Natural Earth 1:110m, public domain), built by
tests/tools/build_world.py into pidreams/assets/world_110m.json; and the detailed outline for the
zoomed-in globe (Natural Earth 1:50m, every ~6 km), built by tests/tools/build_world_detail.py."""

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np

_FILE = Path(__file__).resolve().parents[1] / "assets" / "world_110m.json"
_OUTLINE = Path(__file__).resolve().parents[1] / "assets" / "world_50m_outline.npy"


@lru_cache(maxsize=1)
def load() -> dict:
    data = json.loads(_FILE.read_text(encoding="utf-8"))
    data["border"] = np.radians(np.asarray(data["border"], dtype=np.float32))     # (n, 2) lon, lat
    data["land"] = np.radians(np.asarray(data["land"], dtype=np.float32))
    for c in data["countries"]:
        c["arrays"] = [np.asarray(r, dtype=np.float64) for r in c["rings"]]
    return data


@lru_cache(maxsize=1)
def outline() -> np.ndarray:
    """(n, 2) lon, lat in radians of the detailed coast and borders (stored in hundredths of a degree)."""
    return np.radians(np.load(_OUTLINE).astype(np.float32) / 100)


def _inside(lon: float, lat: float, ring: np.ndarray) -> bool:
    x, y = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    hit = ((y > lat) != (y2 > lat)) & (lon < (x2 - x) * (lat - y) / (y2 - y + 1e-12) + x)
    return bool(hit.sum() % 2)


def country_at(lat: float, lon: float) -> dict | None:
    """The country under a point (degrees), or None over the sea."""
    for c in load()["countries"]:
        for ring in c["arrays"]:
            if (ring[:, 0].min() <= lon <= ring[:, 0].max() and ring[:, 1].min() <= lat <= ring[:, 1].max()
                    and _inside(lon, lat, ring)):
                return {"name": c["name"], "iso": c["iso"]}
    return None


def _plain(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch))


def country_by_name(name: str) -> dict | None:
    """{name, iso, lat, lon}; the point is the middle of the country's largest outline."""
    target = _plain(name.strip())
    for c in load()["countries"]:
        if _plain(c["name"]) == target:
            ring = max(c["arrays"], key=len)
            lon, lat = ring[:, 0].mean(), ring[:, 1].mean()
            return {"name": c["name"], "iso": c["iso"], "lat": float(lat), "lon": float(lon)}
    return None
