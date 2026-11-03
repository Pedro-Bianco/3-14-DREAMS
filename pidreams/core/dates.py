"""Spoken dates become real dates.

The model gets date arithmetic wrong (qwen2.5:14b said "depois de amanhã" on a Friday was
"domingo, 31"), but it repeats the person's words correctly. So tools receive the date as it
was said and this module does the math — the same one for the calendar and for reminders.
"""

import datetime as dt
import re
import unicodedata

from pidreams.core.text import DAYS, MONTHS

_NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
            "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15,
            "vinte": 20, "trinta": 30}
_PERIODS = {"de manha": 9, "pela manha": 9, "de tarde": 15, "a tarde": 15, "pela tarde": 15,
             "de noite": 20, "a noite": 20, "pela noite": 20, "meio dia": 12, "meio-dia": 12}


class InvalidDate(ValueError):
    """Message already in Portuguese, for the model to pass on to the person."""


def _normalize(text: str) -> str:
    without = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[,.;!?]", " ", without)).strip()


def _number(word: str) -> int | None:
    return int(word) if word.isdigit() else _NUMBERS.get(word)


def _hour(t: str) -> dt.time | None:
    m = re.search(r"\b(\d{1,2})\s*(?:h|:|horas?\b)\s*(\d{2})?", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if "da tarde" in t or "da noite" in t:
            hour = hour + 12 if hour < 12 else hour
        if hour < 24 and minute < 60:
            return dt.time(hour, minute)
    m = re.search(r"\b(\d{1,2}|" + "|".join(_NUMBERS) + r") da (manha|tarde|noite)", t)
    if m and _number(m.group(1)):
        hour = _number(m.group(1)) + (12 if m.group(2) != "manha" and _number(m.group(1)) < 12 else 0)
        return dt.time(hour % 24)
    for period, hour in _PERIODS.items():
        if period in t:
            return dt.time(hour)
    return None


def _next_day_of_month(day: int, today: dt.date) -> dt.date:
    year, month = today.year, today.month
    for _ in range(13):
        try:
            data = dt.date(year, month, day)
            if data >= today:
                return data
        except ValueError:
            pass
        month, year = (1, year + 1) if month == 12 else (month + 1, year)
    raise InvalidDate(f"Não existe dia {day} nos próximos meses.")


def _day(t: str, today: dt.date, include_today: bool) -> dt.date | None:
    for phrase, days in (("depois de amanha", 2), ("amanha", 1), ("hoje", 0), ("ontem", -1)):
        if re.search(rf"\b{phrase}\b", t):
            return today + dt.timedelta(days=days)
    m = re.search(r"\bdaqui a (\w+) (dia|dias|semana|semanas)\b", t)
    if m and _number(m.group(1)):
        n = _number(m.group(1))
        return today + dt.timedelta(days=n * (7 if m.group(2).startswith("semana") else 1))
    if re.search(r"\b(semana que vem|proxima semana)\b", t):
        return today + dt.timedelta(days=7 - today.weekday())                  # the following Monday
    for i, name in enumerate(DAYS):
        if re.search(rf"\b{_normalize(name)}(-feira)?\b", t):
            days = (i - today.weekday()) % 7
            return today + dt.timedelta(days=days if days or include_today else 7)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        data = dt.date(year + 2000 if year < 100 else year, int(m.group(2)), int(m.group(1)))
        return data if m.group(3) or data >= today else data.replace(year=today.year + 1)
    m = re.search(r"\b(\d{1,2}) de (" + "|".join(_normalize(x) for x in MONTHS) + r")\b", t)
    if m:
        month = [_normalize(x) for x in MONTHS].index(m.group(2)) + 1
        data = dt.date(today.year, month, int(m.group(1)))
        return data if data >= today else data.replace(year=today.year + 1)
    m = re.search(r"\bdia (\d{1,2})\b", t)
    if m:
        return _next_day_of_month(int(m.group(1)), today)
    return None


def resolve_when(text: str, now: dt.datetime, include_today: bool = False,
                    allow_past: bool = False) -> tuple[dt.date, dt.time | None]:
    """(date, time or None). include_today: "sexta" said on a Friday is today (calendar lookup),
    not next week (reminder). A time alone ("às 15h") is today if it hasn't passed, else tomorrow."""
    t = _normalize(text)
    hour = _hour(t)
    try:
        day = _day(t, now.date(), include_today)
    except ValueError as e:
        raise InvalidDate(f"Não entendi a data '{text}' ({e}).") from None
    if day is None:
        if hour is None:
            raise InvalidDate(f"Não entendi a data '{text}'. Diga, por exemplo, amanhã, sexta, "
                               "dia 12 ou daqui a 3 dias.")
        day = now.date() if hour > now.time() else now.date() + dt.timedelta(days=1)
    if not allow_past and (day < now.date() or (day == now.date() and hour and hour <= now.time())):
        raise InvalidDate(f"'{text}' já passou.")
    return day, hour
