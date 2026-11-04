"""Servidor MCP da Agenda com uma agenda iCal fictícia montada em relação a hoje.

Cobre o que é fácil errar: evento semanal com uma ocorrência cancelada (EXDATE) e outra movida
(RECURRENCE-ID), evento de dia inteiro e fuso horário. O servidor roda pelo protocolo, em memória.
"""

import asyncio
import datetime as dt
import io

import pytest
from mcp import Client

from pidreams.mcp import ical_calendar

TODAY = dt.date.today()
MON = TODAY + dt.timedelta(days=(0 - TODAY.weekday()) % 7 or 7)          # próxima segunda (não hoje)


def _d(day, hour="000000"):
    return day.strftime("%Y%m%d") + "T" + hour


def _ics() -> bytes:
    tomorrow = TODAY + dt.timedelta(days=1)
    weekly_start = MON - dt.timedelta(days=28)
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//teste//PI dreams//PT
BEGIN:VTIMEZONE
TZID:America/Sao_Paulo
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:-0300
TZOFFSETTO:-0300
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:dentista@teste
DTSTART;TZID=America/Sao_Paulo:{_d(tomorrow, "100000")}
DTEND;TZID=America/Sao_Paulo:{_d(tomorrow, "110000")}
SUMMARY:Dentista Fictício
LOCATION:Rua Exemplo, 100
END:VEVENT
BEGIN:VEVENT
UID:semanal@teste
DTSTART;TZID=America/Sao_Paulo:{_d(weekly_start, "090000")}
DTEND;TZID=America/Sao_Paulo:{_d(weekly_start, "100000")}
RRULE:FREQ=WEEKLY;BYDAY=MO
EXDATE;TZID=America/Sao_Paulo:{_d(MON, "090000")}
SUMMARY:Reunião do projeto Ipê
END:VEVENT
BEGIN:VEVENT
UID:semanal@teste
RECURRENCE-ID;TZID=America/Sao_Paulo:{_d(MON + dt.timedelta(days=7), "090000")}
DTSTART;TZID=America/Sao_Paulo:{_d(MON + dt.timedelta(days=8), "140000")}
DTEND;TZID=America/Sao_Paulo:{_d(MON + dt.timedelta(days=8), "150000")}
SUMMARY:Reunião do projeto Ipê (remarcada)
END:VEVENT
BEGIN:VEVENT
UID:aniversario@teste
DTSTART;VALUE=DATE:{(TODAY + dt.timedelta(days=3)).strftime("%Y%m%d")}
DTEND;VALUE=DATE:{(TODAY + dt.timedelta(days=4)).strftime("%Y%m%d")}
SUMMARY:Aniversário da Ana
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode("utf-8")


@pytest.fixture(autouse=True)
def fake_calendar(monkeypatch):
    monkeypatch.setitem(ical_calendar._cache, "calendar", None)
    monkeypatch.setattr(ical_calendar.urllib.request, "urlopen", lambda *_a, **_k: io.BytesIO(_ics()))
    monkeypatch.setenv("CALENDAR_URL", "https://calendar.example.org/basic.ics")


def _call(tool, arguments):
    async def run():
        async with Client(ical_calendar.SERVER) as client:
            r = await client.call_tool(tool, arguments)
            return "\n".join(b.text for b in r.content)
    return asyncio.run(run())


def test_resolve_datas_faladas():
    thursday = dt.date(2026, 10, 29)                                      # uma quinta-feira
    assert ical_calendar.resolve_day("amanhã", thursday) == dt.date(2026, 10, 30)
    assert ical_calendar.resolve_day("sexta", thursday) == dt.date(2026, 10, 30)
    assert ical_calendar.resolve_day("quinta-feira", thursday) == thursday        # hoje, se for o dia
    assert ical_calendar.resolve_day("segunda", thursday) == dt.date(2026, 11, 2)
    assert ical_calendar.resolve_day("2026-12-25", thursday) == dt.date(2026, 12, 25)
    assert ical_calendar.resolve_day("25/12", thursday) == dt.date(2026, 12, 25)


def test_amanha_com_horario_e_local():
    text = _call("eventos", {"inicio": "amanhã"})
    assert "10:00–11:00: Dentista Fictício — Rua Exemplo, 100" in text


def test_recorrencia_com_cancelada_e_movida():
    text = _call("eventos", {"inicio": MON.isoformat(), "dias": 14})
    assert text.count("Reunião do projeto Ipê") == 1                  # cancelada e movida fora
    assert "14:00–15:00: Reunião do projeto Ipê (remarcada)" in text
    assert "terça" in text


def test_dia_inteiro_e_busca_sem_acento():
    text = _call("buscar_eventos", {"texto": "aniversario"})
    assert "dia todo: Aniversário da Ana" in text
    assert "Nenhum compromisso com 'formatura'" in _call("buscar_eventos", {"texto": "formatura"})


def test_somente_leitura_e_link_invalido():
    async def list_items():
        async with Client(ical_calendar.SERVER) as client:
            return {t.name: t.annotations.read_only_hint for t in (await client.list_tools()).tools}
    assert asyncio.run(list_items()) == {"eventos": True, "buscar_eventos": True}
    assert "iCal" in ical_calendar.check_link("https://calendar.google.com/calendar/u/0/r")
    assert ical_calendar.check_link("https://calendar.example.org/basic.ics") is None


def test_calendar_is_downloaded_once_within_the_cache_window(monkeypatch):
    downloads = []
    monkeypatch.setattr(ical_calendar.urllib.request, "urlopen",
                        lambda *_a, **_k: downloads.append(1) or io.BytesIO(_ics()))
    ical_calendar._calendar()
    ical_calendar._calendar()
    assert len(downloads) == 1
