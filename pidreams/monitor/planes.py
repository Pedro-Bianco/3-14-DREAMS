"""Planes layer of the monitor: where each aircraft is now, its trail and which region to query.

No Tk here, so it is tested without a window; pidreams/ui/globe.py draws it. The source gives a
position every ~10 s; between them each plane moves on by its speed and heading (at 900 km/h it
covers 2.5 km in 10 s, a visible jump when zoomed in), and a new position is blended in over
~2 s instead of snapping. Everything lives in memory only.
"""

import math
from collections import deque

import numpy as np

EARTH_KM = 6371.0
KNOT_KM_S = 1.852 / 3600
STALE_S = 60.0               # no new position for this long: the plane is no longer drawn
BLEND_S = 2.0                # a new position is blended in over this time
TRAIL_EVERY_S = 5.0
TRAIL_MAX = 90               # ~7.5 min of path
MIN_ZOOM = 6.0               # below this the 460 km region is too small on screen (research R2)
SETTLE_S = 1.5               # the view must rest this long before the region changes
MOVE_KM = 100.0              # and its centre must have moved this far


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(np.subtract(lon2, lon1)) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def advance(lat, lon, track_deg, km):
    """Where a plane gets after `km` along its heading (great circle); degrees in and out."""
    p, l, t, d = np.radians(lat), np.radians(lon), np.radians(track_deg), np.asarray(km) / EARTH_KM
    p2 = np.arcsin(np.sin(p) * np.cos(d) + np.cos(p) * np.sin(d) * np.cos(t))
    l2 = l + np.arctan2(np.sin(t) * np.sin(d) * np.cos(p), np.cos(d) - np.sin(p) * np.sin(p2))
    return np.degrees(p2), (np.degrees(l2) + 540) % 360 - 180


def region_for(lat0: float, lon0: float, zoom: float, current, settled_s: float):
    """(lat, lon) of the region to query, or None. Keeps `current` while the view moves or stays close."""
    if zoom < MIN_ZOOM:
        return None
    if current is not None and (settled_s < SETTLE_S or distance_km(*current, lat0, lon0) <= MOVE_KM):
        return current
    if settled_s < SETTLE_S:
        return None
    return (lat0, lon0)


class Tracker:
    """The aircraft of one region, by transponder code."""

    def __init__(self):
        self.clear()

    def clear(self) -> None:
        self.hexes: list[str] = []
        self.info: list[dict] = []
        self._base = np.zeros((0, 3))          # lat, lon, time of the fix
        self._motion = np.zeros((0, 2))        # speed (km/s), track (deg); 0/0 when unknown
        self._corr = np.zeros((0, 2))          # lat/lon offset being blended away
        self._corr_t = np.zeros(0)
        self._trails: dict[str, deque] = {}
        self._trail_t = -math.inf
        self._trail_arrays = None             # built once per new trail point, not per frame (22 ms for 72k points)

    def __len__(self) -> int:
        return len(self.hexes)

    def _estimate(self, now: float) -> tuple[np.ndarray, np.ndarray]:
        lat, lon = advance(self._base[:, 0], self._base[:, 1], self._motion[:, 1],
                           self._motion[:, 0] * np.maximum(0, now - self._base[:, 2]))
        fade = np.clip(1 - (now - self._corr_t) / BLEND_S, 0, 1)
        return lat + self._corr[:, 0] * fade, (lon + self._corr[:, 1] * fade + 540) % 360 - 180

    def update(self, aircraft: list[dict], now: float) -> None:
        """New data from the source; `now` is the clock of the same frame loop."""
        old = dict(zip(self.hexes, zip(*self._estimate(now)))) if self.hexes else {}
        keep = {h: (self.info[i], self._base[i], self._motion[i]) for i, h in enumerate(self.hexes)
                if now - self._base[i, 2] <= STALE_S}
        for a in aircraft:
            if a.get("hex"):
                speed = (a.get("speed_kt") or 0) * KNOT_KM_S if a.get("track") is not None else 0.0
                keep[a["hex"]] = (a, np.array([a["lat"], a["lon"], now - (a.get("fix_age_s") or 0)]),
                                  np.array([speed, a.get("track") or 0.0]))
        keep = {h: v for h, v in keep.items() if now - v[1][2] <= STALE_S}
        self.hexes = list(keep)
        self.info = [v[0] for v in keep.values()]
        self._base = np.array([v[1] for v in keep.values()]).reshape(-1, 3)
        self._motion = np.array([v[2] for v in keep.values()]).reshape(-1, 2)
        self._corr, self._corr_t = np.zeros((len(keep), 2)), np.full(len(keep), now)
        if old and len(keep):
            lat, lon = self._estimate(now)
            for i, h in enumerate(self.hexes):
                if h in old:                    # blend from where it was drawn to the new estimate
                    self._corr[i] = (old[h][0] - lat[i], (old[h][1] - lon[i] + 540) % 360 - 180)
        for h in list(self._trails):
            if h not in keep:
                del self._trails[h]
                self._trail_arrays = None

    def positions(self, now: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(lat, lon, track) of every plane now. Also drops a trail point every TRAIL_EVERY_S."""
        if not self.hexes:
            return np.zeros(0), np.zeros(0), np.zeros(0)
        lat, lon = self._estimate(now)
        if now - self._trail_t >= TRAIL_EVERY_S:
            self._trail_t = now
            for h, la, lo in zip(self.hexes, lat, lon):
                self._trails.setdefault(h, deque(maxlen=TRAIL_MAX)).append((la, lo))
            self._trail_arrays = None
        return lat, lon, self._motion[:, 1]

    def trails(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(lat, lon, age 0 = newest .. 1 = oldest) of every trail point."""
        if self._trail_arrays is None:
            trails = [np.asarray(trail) for trail in self._trails.values() if trail]
            if not trails:
                self._trail_arrays = (np.zeros(0), np.zeros(0), np.zeros(0))
            else:
                arr = np.concatenate(trails)
                ages = np.concatenate([np.arange(len(tr) - 1, -1, -1) / TRAIL_MAX for tr in trails])
                self._trail_arrays = (arr[:, 0], arr[:, 1], ages)
        return self._trail_arrays

    def get(self, i: int) -> dict:
        return self.info[i]

    def index(self, hex_code: str) -> int | None:
        return self.hexes.index(hex_code) if hex_code in self.hexes else None
