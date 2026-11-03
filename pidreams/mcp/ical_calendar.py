"""Google Calendar MCP server, read-only, through the secret iCal address.

Started by the app (`--mcp agenda`); the address arrives through an environment variable (it lives
in the secret store: whoever has the link can read the calendar). Recurring events, exceptions and moved
occurrences are handled by recurring-ical-events — the part that is easy to get wrong by hand. Dates are
resolved here ("hoje", "amanhã", "sexta", YYYY-MM-DD): the model does not need to know what day it is.
"""

import datetime as dt
import os
import time
import unicodedata
import urllib.request

import icalendar
import recurring_ical_events
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from pidreams.core.dates import InvalidDate, resolve_when
from pidreams.core.text import date_in_words

_CACHE_S = 300                  # downloads the calendar at most every 5 min
_MAX_EVENTS = 25
_cache: dict = {"at": 0.0, "calendar": None}

SERVER = MCPServer(
    "agenda",
    instructions=("Agenda do Google do usuário, só leitura. Para 'o que tenho amanhã/sexta/dia 12' use "
                  "eventos; para achar um compromisso pelo nome use buscar_eventos. Não é possível "
                  "criar nem mudar eventos: diga isso se pedirem."))


def _strip_accents(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower().strip()


def _calendar() -> icalendar.Calendar:
    if _cache["calendar"] is not None and time.time() - _cache["at"] < _CACHE_S:
        return _cache["calendar"]
    url = os.environ.get("CALENDAR_URL", "")
    try:
        with urllib.request.urlopen(url, timeout=20) as reply:
            calendar = icalendar.Calendar.from_ical(reply.read())
    except Exception as e:
        raise ToolError(f"Não consegui ler a agenda ({e}). Confira a internet ou o link na aba Conexões.") from None
    _cache.update(at=time.time(), calendar=calendar)
    return calendar


def check_link(url: str) -> str | None:
    """For the connections screen: None if the link is a calendar, otherwise the message for the person."""
    if not url.startswith("https://") or ".ics" not in url:
        return "Cole o \"Endereço secreto no formato iCal\" (começa com https:// e termina em .ics)."
    try:
        with urllib.request.urlopen(url, timeout=20) as reply:
            icalendar.Calendar.from_ical(reply.read())
        return None
    except Exception as e:
        return f"Esse link não abriu uma agenda ({e})."


def resolve_day(texto: str, today: dt.date) -> dt.date:
    """In the calendar, "sexta" said on a Friday is today and past dates are valid (looking up yesterday)."""
    try:
        return resolve_when(texto or "hoje", dt.datetime.combine(today, dt.time()),
                               include_today=True, allow_past=True)[0]
    except InvalidDate as e:
        raise ToolError(str(e)) from None


def _line(event, tz) -> tuple:
    inicio, end = event.get("DTSTART").dt, event.get("DTEND").dt if event.get("DTEND") else None
    title = str(event.get("SUMMARY", "(sem título)"))
    local = f" — {event.get('LOCATION')}" if event.get("LOCATION") else ""
    if not isinstance(inicio, dt.datetime):                 # evento de dia inteiro
        return (dt.datetime.combine(inicio, dt.time(), tz), f"{date_in_words(inicio)}, dia todo: {title}{local}")
    inicio = inicio.astimezone(tz) if inicio.tzinfo else inicio.replace(tzinfo=tz)
    time_str = inicio.strftime("%H:%M")
    if isinstance(end, dt.datetime):
        time_str += "–" + (end.astimezone(tz) if end.tzinfo else end.replace(tzinfo=tz)).strftime("%H:%M")
    return (inicio, f"{date_in_words(inicio.date())}, {time_str}: {title}{local}")


def _list(eventos, tz) -> str:
    lines = sorted((_line(e, tz) for e in eventos), key=lambda x: x[0])
    cutoff = f"\n[e mais {len(lines) - _MAX_EVENTS} evento(s)]" if len(lines) > _MAX_EVENTS else ""
    return "\n".join(texto for _, texto in lines[:_MAX_EVENTS]) + cutoff


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
def eventos(inicio: str = "hoje", dias: int = 1) -> str:
    """Compromissos a partir de um dia. inicio: hoje, amanhã, depois de amanhã, um dia da semana
    (segunda…domingo = o próximo) ou AAAA-MM-DD; dias: quantos dias a partir dele (7 = a semana)."""
    tz = dt.datetime.now().astimezone().tzinfo
    first = resolve_day(inicio, dt.date.today())
    dias = max(1, min(int(dias), 62))
    a = dt.datetime.combine(first, dt.time(), tz)
    found = recurring_ical_events.of(_calendar()).between(a, a + dt.timedelta(days=dias))
    period = date_in_words(first) + (f" a {date_in_words(first + dt.timedelta(days=dias - 1))}" if dias > 1 else "")
    return _list(found, tz) if found else f"Nenhum compromisso em {period}."


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
def buscar_eventos(texto: str, dias_a_frente: int = 120, dias_atras: int = 30) -> str:
    """Acha compromissos pelo nome, local ou descrição (ex.: dentista, reunião do projeto),
    entre dias_atras dias atrás e dias_a_frente dias à frente."""
    tz = dt.datetime.now().astimezone().tzinfo
    now = dt.datetime.now(tz)
    wanted = _strip_accents(texto)
    found = [e for e in recurring_ical_events.of(_calendar()).between(
        now - dt.timedelta(days=max(0, int(dias_atras))), now + dt.timedelta(days=max(1, int(dias_a_frente))))
        if wanted in _strip_accents(" ".join(str(e.get(c, "")) for c in ("SUMMARY", "LOCATION", "DESCRIPTION")))]
    return _list(found, tz) if found else f"Nenhum compromisso com '{texto}'."
