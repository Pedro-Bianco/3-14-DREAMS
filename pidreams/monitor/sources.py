"""Online sources of the monitor, all free and without a key. Each function returns data or
raises SourceError with a short Portuguese sentence for the user; one source failing never
takes the others down. Every source here allows this use (terms and robots.txt checked 2026-11-03).

- news: the feeds the outlets publish (Agência Brasil, BBC News Brasil, DW, ONU News, RTP: ~200
  recent items in 1.3 s), filtered by the place; GDELT as the deep research's fallback, one request every 5 s.
- places and weather: Open-Meteo. Earthquakes: USGS feed. Flights: adsb.lol (open data).
- radios: Radio Browser, MP3 only (65% of the stations with coordinates; see radio.py); its servers
  are looked up in DNS, as its rules ask.
- orbits and catalog: CelesTrak, kept on disk (it blocks repeated downloads within ~2 h).
"""

import datetime as dt
import html
import json
import logging
import random
import re
import socket
import time
import unicodedata
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


def cache_age(name: str) -> float | None:
    """Seconds since the disk copy of a source was saved; None without a copy."""
    file = paths.cache_dir("monitor") / f"{name}.json"
    return time.time() - file.stat().st_mtime if file.is_file() else None


def _cached(name: str, max_age: float, fetch, what: str):
    """(data, age in seconds) from the disk cache, fetching again when older than max_age. When
    the fetch fails, an old copy is still better than nothing (satellites keep moving offline)."""
    file = paths.cache_dir("monitor") / f"{name}.json"
    age = cache_age(name)
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

# Feeds the outlets publish for news readers, all allowed by their robots.txt (checked 2026-11-03).
# Search pages of news aggregators are not used: Google News' robots.txt forbids programs.
FEEDS = [
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
    ("BBC News Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
    ("DW Brasil", "https://rss.dw.com/rdf/rss-br-all"),
    ("ONU News", "https://news.un.org/feed/subscribe/pt/news/all/rss.xml"),
    ("RTP", "https://www.rtp.pt/noticias/rss"),
]
FEEDS_MAX_AGE = 15 * 60
_GDELT_GAP_S = 5             # GDELT's own rule: one request every 5 seconds
_gdelt_last = 0.0


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def parse_feed(raw: bytes, outlet: str) -> list[dict]:
    """Items of an RSS 2.0 or RDF feed: [{title, source, date, ts, link, summary}]."""
    items = []
    for item in ET.fromstring(raw).iter():
        if item.tag.split("}")[-1] != "item":
            continue
        fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in item}
        try:
            when = (parsedate_to_datetime(fields["pubDate"]) if fields.get("pubDate")
                    else dt.datetime.fromisoformat(fields["date"].replace("Z", "+00:00")))
        except (KeyError, TypeError, ValueError):
            when = None
        items.append({"title": html.unescape(fields.get("title", "")), "source": outlet,
                      "date": when.strftime("%d/%m %H:%M") if when else "", "ts": when.timestamp() if when else 0,
                      "link": fields.get("link", ""),
                      "summary": html.unescape(re.sub(r"<[^>]+>", " ", fields.get("description", ""))).strip()[:300]})
    return items


def _fetch_feeds() -> list[dict]:
    items = []
    for outlet, url in FEEDS:
        try:
            items += parse_feed(_get(url, 15), outlet)
        except Exception as e:
            log.warning(f"[Monitor] feed {outlet}: {e}")
    if not items:
        raise SourceError("Nenhum feed de notícias respondeu.")
    return items


def matching(items: list[dict], terms: str) -> list[dict]:
    """Items whose title or summary name every significant word of `terms` (accents ignored), newest first."""
    words = [w for w in re.findall(r"\w+", _plain(terms)) if len(w) >= 3 and w not in _STOPWORDS]
    if not words:
        return []
    found = [i for i in items
             if all(re.search(rf"\b{re.escape(w)}", _plain(i["title"] + " " + i["summary"])) for w in words)]
    unique = {i["link"] or i["title"]: i for i in found}
    return sorted(unique.values(), key=lambda i: -i["ts"])


_STOPWORDS = {"dos", "das", "nos", "nas", "com", "para", "por", "sobre", "que", "uma", "the", "and"}


def parse_gdelt(raw: bytes, limit: int = 10) -> list[dict]:
    articles = json.loads(raw or b"{}").get("articles", [])
    return [{"title": a.get("title", ""), "source": a.get("domain", ""), "date": a.get("seendate", "")[:8],
             "ts": 0, "link": a.get("url", ""), "summary": ""}
            for a in articles[:limit]]


def _gdelt(terms: str, timespan: str) -> list[dict]:
    """Fallback: GDELT is free for any use with a citation, one request every 5 s at most."""
    global _gdelt_last
    wait = _gdelt_last + _GDELT_GAP_S - time.time()
    if wait > 0:
        time.sleep(wait)
    _gdelt_last = time.time()
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(
        {"query": f"{terms} sourcelang:portuguese", "mode": "ArtList", "format": "json", "maxrecords": 10,
         "timespan": timespan, "sort": "HybridRel"})
    return parse_gdelt(_get(url, 20))


def news_about(terms: str, limit: int = 10, timespan: str = "24h", gdelt: bool = True) -> list[dict]:
    """Recent headlines naming `terms`: the outlets' feeds first, GDELT when they have none (unless
    gdelt=False: a spoken answer cannot wait for its 5 s gap and frequent 429s)."""
    try:
        items, _age = _cached("news_feeds", FEEDS_MAX_AGE, _fetch_feeds, "as notícias")
    except SourceError:
        items = []
    found = matching(items, terms)[:limit]
    if found or not gdelt:
        return found
    try:
        return _gdelt(terms, timespan)
    except Exception as e:
        if not items:
            raise SourceError("Não consegui as notícias agora (sem conexão ou as fontes não responderam).") from e
        log.warning(f"[Monitor] GDELT: {e}")
        return []


def news(place_name: str) -> list[dict]:
    """Recent headlines about a place: [{title, source, date, link, ...}]. The outlets' feeds only:
    the monitor answers by voice, and the GDELT fallback once held a reply for 22 s (2026-11-04)."""
    return news_about(place_name, gdelt=False)


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


def quakes(max_age: float = QUAKES_MAX_AGE) -> list[dict]:
    """M2.5+ earthquakes of the last 24 h, strongest first."""
    data, _age = _cached("quakes", max_age, lambda: parse_quakes(
        _get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson")), "os terremotos")
    return data


# ── flights ──

def parse_flights(raw: bytes) -> list[dict]:
    return [{"callsign": (a.get("flight") or a.get("r") or a.get("hex", "")).strip(), "lat": a["lat"], "lon": a["lon"],
             "alt": a.get("alt_baro"), "speed": a.get("gs"), "type": a.get("t", "")}
            for a in json.loads(raw).get("ac", []) if "lat" in a and "lon" in a]


def parse_aircraft(raw: bytes, ground: bool = False) -> list[dict]:
    """Aircraft for the planes layer, without the ones without a position; those on the ground only
    when asked (looking up one flight: "it is on the ground at...")."""
    out = []
    for a in json.loads(raw).get("ac", []):
        if "lat" not in a or "lon" not in a or (a.get("alt_baro") == "ground" and not ground):
            continue
        alt = a.get("alt_baro")
        out.append({"hex": a.get("hex", ""), "callsign": (a.get("flight") or "").strip(), "reg": a.get("r", ""),
                    "type": a.get("t", ""), "lat": a["lat"], "lon": a["lon"],
                    "alt_ft": alt if isinstance(alt, (int, float)) else None, "speed_kt": a.get("gs"),
                    "track": a.get("track"), "fix_age_s": a.get("seen_pos", a.get("seen", 0.0)),
                    "on_ground": a.get("alt_baro") == "ground"})
    return out


PLANES_RADIUS_NM = 250       # the source's largest radius (~460 km)


def aircraft(lat: float, lon: float) -> list[dict]:
    """Aircraft in flight within 250 nautical miles, for the planes layer."""
    try:
        return parse_aircraft(_get(f"https://api.adsb.lol/v2/point/{lat:.3f}/{lon:.3f}/{PLANES_RADIUS_NM}", 15))
    except Exception as e:
        raise SourceError("Não consegui os aviões agora (sem conexão ou a fonte não respondeu).") from e


def flight(code: str) -> list[dict]:
    """A flight by its number ("GLO1808", "glo 1808"): the aircraft using it now, if it is being seen."""
    callsign = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    try:
        return parse_aircraft(_get(f"https://api.adsb.lol/v2/callsign/{callsign}", 15), ground=True)
    except Exception as e:
        raise SourceError("Não consegui procurar o voo agora (sem conexão ou a fonte não respondeu).") from e


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


def radios(max_age: float = RADIOS_MAX_AGE) -> list[dict]:
    data, _age = _cached("radios", max_age, _fetch_radios, "as rádios")
    return data


# ── satellites ──

def orbits(max_age: float = ORBITS_MAX_AGE) -> tuple[list[dict], float]:
    """(OMM records of the active satellites, age of the copy in seconds)."""
    return _cached("orbits", max_age, lambda: json.loads(_get(
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json", 60)), "as órbitas dos satélites")


def satellite_owners(max_age: float = CATALOG_MAX_AGE) -> dict[str, str]:
    """{NORAD id: owner code}, from CelesTrak's catalog."""
    data, _age = _cached("satcat", max_age, lambda: {
        str(r["NORAD_CAT_ID"]): r.get("OWNER", "") for r in json.loads(_get(
            "https://celestrak.org/satcat/records.php?GROUP=active&FORMAT=json", 60))}, "o catálogo de satélites")
    return data
