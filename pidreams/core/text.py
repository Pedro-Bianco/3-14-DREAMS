"""Text shared by speech and chat: cleanup and dates in words."""

import datetime as dt
import re

# The conduct rules forbid emojis, but the model sometimes slips (seen in the chat on
# 2026-10-16). TTS always stripped them; the chat strips them too.
_EMOJI = re.compile("[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FFFF️]+")


def remove_emojis(text: str) -> str:
    return re.sub(r" {2,}", " ", _EMOJI.sub("", text))


DAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro")


def date_in_words(day: dt.date, year: bool = False) -> str:
    """"sexta, 30 de outubro" (year=True: "sexta-feira, 30 de outubro de 2026")."""
    name = DAYS[day.weekday()] + ("-feira" if year and day.weekday() < 5 else "")
    return f"{name}, {day.day} de {MONTHS[day.month - 1]}" + (f" de {day.year}" if year else "")


def today_in_words(today: dt.date | None = None) -> str:
    """Includes tomorrow: the model gets date arithmetic wrong ("depois de amanhã" on a
    Friday came out as "domingo, 31", seen on qwen2.5:14b)."""
    today = today or dt.date.today()
    return f"{date_in_words(today, year=True)} (amanhã é {date_in_words(today + dt.timedelta(days=1))})"


def now_in_words(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    return f"{today_in_words(now.date())}, agora são {now:%H:%M}"


# Opening and closing a mode (Monitoramento, Pesquisa profunda) is decided by code. Fixed phrase
# lists missed free wording ("vamos abrir o modo de monitoramento?", "sair do modo de
# monitoramento"): the model then tried open_app or only explained how to close.
_OPEN_VERB = re.compile(r"\b(abr\w*|ativ\w*|lig\w*|entr\w*|mostr\w*|inici\w*|vamos|quero)\b")
_CLOSE_VERB = re.compile(r"\b(fech\w*|sai\w*|sair|deslig\w*|encerr\w*)\b")


def asks_to_open(phrase: str, mode: str, max_words: int = 8) -> bool:
    """A short sentence naming the mode with an opening verb and no closing one."""
    return (mode in phrase and len(phrase.split()) <= max_words
            and bool(_OPEN_VERB.search(phrase)) and not _CLOSE_VERB.search(phrase))


def asks_to_close(phrase: str, mode: str, max_words: int = 8) -> bool:
    return mode in phrase and len(phrase.split()) <= max_words and bool(_CLOSE_VERB.search(phrase))
