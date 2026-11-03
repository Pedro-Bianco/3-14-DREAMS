"""Online sources of the monitor, all free and without a key. Each function returns data or
raises SourceError with a short Portuguese sentence for the user; one source failing never
takes the others down. Measured on 2026-11-02:

- news: Google News RSS (Portuguese, by place, 0.4-0.8 s); GDELT as the fallback (it answered
  "429 Too Many Requests" all day, even with 30 s between calls).
- places and weather: Open-Meteo. Earthquakes: USGS feed. Flights: adsb.lol (open data).
- radios: Radio Browser, MP3 only (65% of the stations with coordinates; see radio.py); its servers
  are looked up in DNS, as its rules ask.
- orbits and catalog: CelesTrak, kept on disk (it blocks repeated downloads within ~2 h).
"""

import json
import logging
import random
import socket
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from functools import lru_cache

from pidreams import USER_AGENT
from pidreams.core import paths

log = logging.getLogger(__name__)

_AGENT = {"User-Agent": USER_AGENT}
ORBITS_MAX_AGE = 6 * 3600
CATALOG_MAX_AGE = RADIOS_MAX_AGE = 7 * 24 * 3600
QUAKES_MAX_AGE = 5 * 60


class SourceError(Exception):
    """Message already written for the person."""


def _get(url: str, timeout: float = 15) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_AGENT), timeout=timeout) as resp:
        return resp.read()


def _cached(name: str, max_age: float, fetch, what: str):
    """(data, age in seconds) from the disk cache, fetching again when older than max_age. When
    the fetch fails, an old copy is still better than nothing (satellites keep moving offline)."""
    file = paths.cache_dir("monitor") / f"{name}.json"
    age = time.time() - file.stat().st_mtime if file.is_file() else None
    if age is not None and age < max_age:
        return json.loads(file.read_text(encoding="utf-8")), age
    try:
        data = fetch()
    except Exception as e:
        log.warning(f"[Monitor] {name}: {e}")
        if age is not None:
            return json.loads(file.read_text(encoding="utf-8")), age
        raise SourceError(f"Não consegui {what} agora (sem conexão ou a fonte não respondeu).") from e
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data, 0.0


# ── places ──

@lru_cache(maxsize=256)
def place(name: str) -> dict:
    """{name, country, lat, lon} of a city, region or country, by its Portuguese name."""
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": name.strip(), "count": 1, "language": "pt", "format": "json"})
    try:
        results = json.loads(_get(url, 10)).get("results") or []
    except Exception as e:
        raise SourceError("Não consegui localizar o lugar agora (sem conexão?).") from e
    if not results:
        raise SourceError(f"Não encontrei nenhum lugar chamado “{name}”.")
    r = results[0]
    return {"name": r["name"], "country": r.get("country", ""), "lat": r["latitude"], "lon": r["longitude"]}


# ── news ──

def parse_google_rss(raw: bytes, limit: int = 10) -> list[dict]:
    items = []
    for item in ET.fromstring(raw).iter("item"):
        source = item.findtext("source") or ""
        title = (item.findtext("title") or "").strip()
        if source and title.endswith(" - " + source):        # Google appends the outlet to the title
            title = title[: -len(source) - 3]
        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "").strftime("%d/%m %H:%M")
        except (TypeError, ValueError):
            date = ""
        items.append({"title": title, "source": source, "date": date, "link": item.findtext("link") or ""})
        if len(items) >= limit:
            break
    return items


def parse_gdelt(raw: bytes, limit: int = 10) -> list[dict]:
    articles = json.loads(raw or b"{}").get("articles", [])
    return [{"title": a.get("title", ""), "source": a.get("domain", ""), "date": a.get("seendate", "")[:8], "link": a.get("url", "")}
            for a in articles[:limit]]


def news(place_name: str) -> list[dict]:
    """Recent headlines (last day) about a place: [{title, source, date, link}]."""
    google = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{place_name} when:1d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})
    try:
        items = parse_google_rss(_get(google, 12))
        if items:
            return items
    except Exception as e:
        log.warning(f"[Monitor] Google News: {e}")
    gdelt = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(
        {"query": place_name, "mode": "ArtList", "format": "json", "maxrecords": 10, "timespan": "24h", "sort": "HybridRel"})
    try:
        return parse_gdelt(_get(gdelt, 20))
    except Exception as e:
        raise SourceError("Não consegui as notícias agora (sem conexão ou as fontes não responderam).") from e


# ── weather ──

_WEATHER = {0: "céu limpo", 1: "quase limpo", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina",
            51: "garoa fraca", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva", 65: "chuva forte",
            71: "neve fraca", 73: "neve", 75: "neve forte", 80: "pancadas de chuva", 81: "pancadas de chuva",
            82: "pancadas fortes", 95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo"}


def describe_weather(code: int) -> str:
    return _WEATHER.get(int(code), "tempo variável")


def weather(lat: float, lon: float) -> dict:
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 3, "timezone": "auto"})
    try:
        d = json.loads(_get(url, 10))
    except Exception as e:
        raise SourceError("Não consegui o clima agora (sem conexão?).") from e
    days = d["daily"]
    return {"now": {"temp": d["current"]["temperature_2m"], "desc": describe_weather(d["current"]["weather_code"]),
                    "wind": d["current"]["wind_speed_10m"]},
            "days": [{"date": days["time"][i], "max": days["temperature_2m_max"][i], "min": days["temperature_2m_min"][i],
                      "desc": describe_weather(days["weather_code"][i]), "rain": days["precipitation_probability_max"][i]}
                     for i in range(len(days["time"]))]}


# ── earthquakes ──

def parse_quakes(raw: bytes) -> list[dict]:
    out = []
    for f in json.loads(raw)["features"]:
        lon, lat, depth = f["geometry"]["coordinates"]
        p = f["properties"]
        out.append({"place": p.get("place") or "", "mag": p.get("mag") or 0.0, "time": p.get("time", 0) // 1000,
                    "lat": lat, "lon": lon, "depth": depth})
    return sorted(out, key=lambda q: -q["mag"])


def quakes() -> list[dict]:
    """M2.5+ earthquakes of the last 24 h, strongest first."""
    data, _age = _cached("quakes", QUAKES_MAX_AGE, lambda: parse_quakes(
        _get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson")), "os terremotos")
    return data


# ── flights ──

def parse_flights(raw: bytes) -> list[dict]:
    return [{"callsign": (a.get("flight") or a.get("r") or a.get("hex", "")).strip(), "lat": a["lat"], "lon": a["lon"],
             "alt": a.get("alt_baro"), "speed": a.get("gs"), "type": a.get("t", "")}
            for a in json.loads(raw).get("ac", []) if "lat" in a and "lon" in a]


def flights(lat: float, lon: float, radius_nm: int = 135) -> list[dict]:
    """Aircraft within ~250 km (135 nautical miles)."""
    try:
        return parse_flights(_get(f"https://api.adsb.lol/v2/point/{lat:.3f}/{lon:.3f}/{radius_nm}", 15))
    except Exception as e:
        raise SourceError("Não consegui os voos agora (sem conexão ou a fonte não respondeu).") from e


# ── radios ──

def parse_radios(raw: bytes) -> list[dict]:
    return [{"name": s["name"].strip(), "country": s.get("country", ""), "iso": s.get("countrycode", ""),
             "lat": s["geo_lat"], "lon": s["geo_long"], "url": s.get("url_resolved") or s["url"],
             "votes": s.get("clickcount", 0)}
            for s in json.loads(raw)
            if s.get("geo_lat") is not None and s.get("geo_long") is not None and s.get("codec") == "MP3"]


def radio_servers() -> list[str]:
    """Radio Browser servers in random order. Its rules: never hard-code one server (they change);
    look them up in DNS (all.api.radio-browser.info) and name each address by reverse lookup."""
    addresses = {a[4][0] for a in socket.getaddrinfo("all.api.radio-browser.info", 443, proto=socket.IPPROTO_TCP)}
    names = set()
    for address in addresses:
        try:
            names.add(socket.gethostbyaddr(address)[0])
        except OSError:
            pass
    servers = list(names)
    random.shuffle(servers)
    return servers


def _fetch_radios() -> list[dict]:
    query = urllib.parse.urlencode({"codec": "MP3", "has_geo_info": "true", "hidebroken": "true",
                                    "order": "clickcount", "reverse": "true", "limit": 20000})
    servers = radio_servers()
    for i, server in enumerate(servers):
        try:
            return parse_radios(_get(f"https://{server}/json/stations/search?{query}", 90))
        except Exception as e:
            if i == len(servers) - 1:
                raise
            log.warning(f"[Monitor] radios at {server}: {e}; trying the next server")
    raise SourceError("Nenhum servidor de rádios encontrado.")


def radios() -> list[dict]:
    data, _age = _cached("radios", RADIOS_MAX_AGE, _fetch_radios, "as rádios")
    return data


# ── satellites ──

def orbits() -> tuple[list[dict], float]:
    """(OMM records of the active satellites, age of the copy in seconds)."""
    return _cached("orbits", ORBITS_MAX_AGE, lambda: json.loads(_get(
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json", 60)), "as órbitas dos satélites")


def satellite_owners() -> dict[str, str]:
    """{NORAD id: owner code}, from CelesTrak's catalog."""
    data, _age = _cached("satcat", CATALOG_MAX_AGE, lambda: {
        str(r["NORAD_CAT_ID"]): r.get("OWNER", "") for r in json.loads(_get(
            "https://celestrak.org/satcat/records.php?GROUP=active&FORMAT=json", 60))}, "o catálogo de satélites")
    return data
