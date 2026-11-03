"""Daily briefing when PI opens.

Built by code from the sources that already exist — without going through the model: it is
fast, makes nothing up and does not depend on the persona's mood. The sources run together under
a total limit; one that fails or is slow drops out of the briefing without holding the others.
"""

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable

from pidreams import reminders
from pidreams.core.text import date_in_words

LIMIT_S = 10.0
MAX_REMINDERS = 5
MAX_SENDERS = 3


def greeting(now: dt.datetime, treatment: str = "") -> str:
    hour = now.hour
    text = "Bom dia" if 5 <= hour < 12 else "Boa tarde" if 12 <= hour < 18 else "Boa noite"
    return f"{text}, {treatment}." if treatment else f"{text}."


def weather_phrase(data: dict) -> str:
    return f"Em {data['city']}, {data['temp']} graus, {data['desc'].lower()}."


def calendar_phrase(events_text: str, now: dt.datetime) -> str:
    """From lines like "sexta, 30 de outubro, 10:00–11:00: Dentista — Rua X", keeps what is still ahead today."""
    if events_text.startswith("Nenhum"):
        return "Sua agenda está livre hoje."
    missing = []
    for line in events_text.splitlines():
        m = re.search(r", (\d{2}:\d{2})(?:–\d{2}:\d{2})?: (.+?)(?: — .*)?$", line)
        if m and m.group(1) >= now.strftime("%H:%M"):
            missing.append(f"às {m.group(1)}, {m.group(2)}")
        elif "dia todo:" in line:
            missing.append(line.split("dia todo:", 1)[1].split(" — ")[0].strip() + ", o dia todo")
    if not missing:
        return "Não tem mais nada na agenda hoje."
    return "Na agenda de hoje: " + "; ".join(missing) + "."


def emails_phrase(search_text: str) -> str:
    lines = [l for l in search_text.splitlines() if l.startswith("id ")]
    if not lines:
        return "Nenhum e-mail novo."
    names = []
    for line in lines[:MAX_SENDERS]:
        m = re.search(r"de: (.*?) <", line)
        names.append(m.group(1).strip() if m and m.group(1).strip() else "remetente sem nome")
    how_many = "um e-mail não lido" if len(lines) == 1 else f"{len(lines)} e-mails não lidos"
    last_items = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]
    return f"Você tem {how_many}; {'o mais recente' if len(names) == 1 else 'os mais recentes'} de {last_items}."


def reminders_phrase(items: list[dict], now: dt.datetime) -> str:
    if not items:
        return ""
    spoken = "; ".join(reminders.describe(l, now) for l in items[:MAX_REMINDERS])
    rest = len(items) - MAX_REMINDERS
    label_text = "Lembrete" if len(items) == 1 else "Lembretes"
    return f"{label_text}: {spoken}" + (f"; e mais {rest}." if rest > 0 else ".")


def sources(connections, now: dt.datetime, parts: dict, reminder_items: list[dict]) -> dict[str, Callable[[], str]]:
    """{part: function returning its sentence} for the parts that are on and available.
    No side effects: the briefing on open and the "Hoje" cards both use it."""
    from pidreams import weather
    from pidreams.core.config import CONFIG

    def from_connection(id_, tool, arguments, phrase):
        def source():
            text = connections.call(id_, tool, arguments)
            if text.startswith("Erro") or "não está ativa" in text or "não respondeu" in text:
                raise RuntimeError(text)               # drops out of the briefing
            return phrase(text)
        return source

    sources_map = {}
    if parts.get("clima", True) and CONFIG.weather_city:
        sources_map["clima"] = lambda: weather_phrase(weather.fetch(CONFIG.weather_city))
    active = connections.connected() if connections else []
    if parts.get("agenda", True) and "agenda" in active:
        sources_map["agenda"] = from_connection("agenda", "eventos", {"inicio": "hoje"},
                                                lambda text: calendar_phrase(text, now))
    if parts.get("emails", True) and "gmail" in active:
        sources_map["emails"] = from_connection("gmail", "buscar_emails",
                                                {"so_nao_lidos": True, "desde_dias": 1, "maximo": 20}, emails_phrase)
    if parts.get("lembretes", True):
        sources_map["lembretes"] = lambda: reminders_phrase(reminder_items, now)
    return sources_map


def build(now: dt.datetime, sources_map: dict[str, Callable[[], str]], full_briefing: bool,
           treatment: str = "", limit_s: float = LIMIT_S) -> str:
    """sources: {"clima"|"agenda"|"emails"|"lembretes": function returning the sentence (empty = nothing)}.
    full=False (app reopened the same day): just a short greeting and reminders."""
    order = ["clima", "agenda", "emails", "lembretes"] if full_briefing else ["lembretes"]
    execute = {name: sources_map[name] for name in order if name in sources_map}
    phrases: dict[str, str] = {}
    # No "with": leaving the block would wait for the slow source and the limit would not hold.
    pool = ThreadPoolExecutor(max_workers=max(1, len(execute)))
    upcoming = {pool.submit(function): name for name, function in execute.items()}
    builtin, _ = wait(upcoming, timeout=limit_s)
    pool.shutdown(wait=False, cancel_futures=True)
    for future in builtin:
        try:
            phrases[upcoming[future]] = future.result() or ""
        except Exception:
            pass                             # a failing part drops out of the briefing
    parts = [greeting(now, treatment)]
    if full_briefing:
        parts.append(f"Hoje é {date_in_words(now.date())}.")
    parts += [phrases[n] for n in order if phrases.get(n)]
    return " ".join(parts)
