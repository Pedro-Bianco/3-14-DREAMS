"""Topic of each memory: what groups them in the memory graph.

The e5 vectors alone do not group memories by topic: every memory starts with "O usuário",
and measured on 30 memories in 4 topics only 43-49% of the nearest-neighbor links stayed
inside a topic (chance is ~25%). The chat model tagging a batch from a fixed list got 28 of 30
(2026-10-31). Tagging runs in batches, only while the assistant is idle, once per memory.
"""

import re
import unicodedata

TOPICS = ("família", "trabalho", "saúde", "rotina", "lazer", "animais", "casa", "finanças", "estudos", "outros")
PROFILE = "perfil"           # profile memories get it without asking the model
UNTAGGED = "sem assunto"     # shown until the model tags it
BATCH = 20                   # memories per call: ~3 s of model time, short enough not to hold a reply for long

PROMPT = """\
Classifique cada memória sobre o usuário em UM assunto desta lista: {topics}.
Responda uma linha por memória, no formato: número. assunto

{items}"""


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


_BY_PLAIN = {_plain(t): t for t in TOPICS}


def prompt_for(texts: list[str]) -> str:
    return PROMPT.format(topics=", ".join(TOPICS), items="\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))


def parse_topics(raw: str, n: int) -> list[str]:
    """One topic per memory, in order. A missing line or a topic outside the list → "outros"."""
    found = {}
    for m in re.finditer(r"^\s*(\d+)\s*[.)\-:]\s*(.+?)\s*$", raw or "", re.MULTILINE):
        found[int(m.group(1))] = _BY_PLAIN.get(_plain(m.group(2)).strip(" .*"), "outros")
    return [found.get(i, "outros") for i in range(1, n + 1)]
