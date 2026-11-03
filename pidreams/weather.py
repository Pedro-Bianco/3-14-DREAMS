"""Current weather from Open-Meteo (no key). Used by the panel and by the briefing on open.

It was wttr.in until 2026-11-03, when it refused every connection for hours (WinError 10061)
and the panel stayed on "obtendo o clima…"; the monitor already used Open-Meteo without failures.
"""

from pidreams.monitor import sources


def fetch(city: str, limit_s: float = 8) -> dict:
    """{'city', 'temp', 'desc'}; raises if it cannot get it."""
    place = sources.place(city)
    now = sources.weather(place["lat"], place["lon"])["now"]
    return {"city": city, "temp": f"{now['temp']:.0f}", "desc": now["desc"]}
