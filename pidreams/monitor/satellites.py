"""Active satellites: CelesTrak orbits → positions now, with sgp4 vectorized over all of them.
Measured: 16 847 satellites in 5 ms; the ISS 18 km from the public tracker wheretheiss.at
(2026-11-02). Latitude is geocentric (a few km from the map's), which the globe cannot show."""

import math
from datetime import datetime, timezone

import numpy as np
from sgp4 import omm
from sgp4.api import Satrec, SatrecArray, jday

EARTH_KM = 6371.0
STALE_AFTER_S = 3 * 24 * 3600      # older orbits drift by tens of km a day for low satellites

TYPES = {"internet": "Internet", "navegacao": "Navegação", "clima": "Clima", "estacao": "Estações espaciais", "outros": "Outros"}
_PREFIXES = {
    "internet": ("STARLINK", "ONEWEB", "KUIPER", "QIANFAN", "GUOWANG", "IRIDIUM", "GLOBALSTAR", "ORBCOMM"),
    "navegacao": ("NAVSTAR", "GPS", "GLONASS", "COSMOS 25", "GALILEO", "GSAT0", "BEIDOU", "IRNSS", "QZS"),
    "clima": ("NOAA", "GOES", "METEOSAT", "METOP", "HIMAWARI", "FENGYUN", "FY-", "SUOMI", "JPSS", "DMSP", "ELEKTRO", "METEOR"),
    "estacao": ("ISS (", "CSS (", "TIANHE", "WENTIAN", "MENGTIAN"),
}
OWNERS = {"US": "Estados Unidos", "PRC": "China", "UK": "Reino Unido", "CIS": "Rússia", "JPN": "Japão", "IT": "Itália",
          "FR": "França", "IND": "Índia", "ESA": "Agência Espacial Europeia", "GER": "Alemanha", "CA": "Canadá",
          "BRAZ": "Brasil", "ISS": "Estação Espacial (vários países)", "SKOR": "Coreia do Sul", "SPN": "Espanha",
          "LUXE": "Luxemburgo", "SES": "SES (Luxemburgo)", "EUTE": "Eutelsat", "ARGN": "Argentina", "ISRA": "Israel",
          "AUS": "Austrália", "TURK": "Turquia", "UAE": "Emirados Árabes", "SAUD": "Arábia Saudita", "MEX": "México"}


# Spoken names → catalog names ("Hubble" matched "HUBBLE 6"; the telescope is "HST").
_ALIASES = [(("CHINESA", "TIANGONG", "TIANHE"), "CSS (TIANHE)"),
            (("ESTAÇÃO ESPACIAL", "ESTACAO ESPACIAL", "ISS"), "ISS (ZARYA)"),
            (("HUBBLE",), "HST")]


def kind_of(name: str) -> str:
    upper = name.upper()
    return next((k for k, prefixes in _PREFIXES.items() if upper.startswith(prefixes)), "outros")


def owner_name(code: str) -> str:
    return OWNERS.get(code, code or "desconhecido")


def _gmst(jd: float, fr: float) -> float:
    """Greenwich sidereal angle: TEME (sgp4's frame) → Earth-fixed."""
    d = jd + fr - 2451545.0
    return math.radians((280.46061837 + 360.98564736629 * d) % 360)


class Satellites:
    def __init__(self, records: list[dict], owners: dict[str, str] | None = None):
        sats, self.names, self.norad = [], [], []
        for r in records:
            s = Satrec()
            try:
                omm.initialize(s, r)
            except (KeyError, ValueError):
                continue
            sats.append(s)
            self.names.append(r.get("OBJECT_NAME", "").strip())
            self.norad.append(str(r.get("NORAD_CAT_ID", "")))
        self._array = SatrecArray(sats) if sats else None
        self.kinds = np.array([kind_of(n) for n in self.names])
        owners = owners or {}
        self.owners = [owner_name(owners.get(n, "")) for n in self.norad]

    def __len__(self) -> int:
        return len(self.names)

    def positions(self, when: datetime | None = None):
        """(lat, lon in radians, altitude km, valid mask) of every satellite at `when` (now)."""
        n = len(self)
        if not n:
            empty = np.zeros(0)
            return empty, empty, empty, empty.astype(bool)
        when = when or datetime.now(timezone.utc)
        jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
        err, r, _v = self._array.sgp4(np.array([jd]), np.array([fr]))
        x, y, z = r[:, 0, 0], r[:, 0, 1], r[:, 0, 2]
        g = _gmst(jd, fr)
        xe, ye = x * math.cos(g) + y * math.sin(g), -x * math.sin(g) + y * math.cos(g)
        radius = np.sqrt(xe ** 2 + ye ** 2 + z ** 2)
        ok = (err[:, 0] == 0) & np.isfinite(radius)
        with np.errstate(invalid="ignore", divide="ignore"):
            lat = np.arctan2(z, np.hypot(xe, ye))
            lon = np.arctan2(ye, xe)
        return lat, lon, radius - EARTH_KM, ok

    def find(self, name: str) -> int | None:
        """Index of a satellite by (part of) its name; "estação espacial" → the ISS."""
        target = name.strip().upper()
        target = next((full for words, full in _ALIASES if any(w in target for w in words)), target)
        exact = [i for i, n in enumerate(self.names) if n.upper() == target]
        if exact:
            return exact[0]
        return next((i for i, n in enumerate(self.names) if target in n.upper()), None)


def load(stale_ok: bool = False) -> tuple[Satellites, float]:
    """(satellites, age of the orbits in seconds); raises SourceError without any copy. stale_ok: the
    copy on disk however old (downloads only when there is none)."""
    from pidreams.monitor import sources
    records, age = sources.orbits(math.inf) if stale_ok else sources.orbits()
    try:
        owners = sources.satellite_owners(math.inf) if stale_ok else sources.satellite_owners()
    except sources.SourceError:
        owners = {}
    return Satellites(records, owners), age
