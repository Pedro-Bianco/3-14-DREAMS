"""Answer only when called by name ("PI, que horas são?"), as an option for the voice mode.

Checked on the transcribed text, no audio model: the speech is already transcribed for the reply.
The accepted spellings of "PI" come from the live measurement (tests/eval/wake_name.py): Whisper
writes the same spoken name in more than one way."""

import re

from pidreams.routines import normalize

# Ways Whisper wrote "PI" at the start of a sentence, after normalize() ("P.I." -> "p i").
# Live measurement (2026-11-09, 18 calls + 11 speeches for others): "Pi" 9x, "P" 2x, "Ih" 1x, "E" 1x;
# 5 calls lost their first words (the test closed the microphone while transcribing). "p" added
# (no sentence starts with the letter alone); "ih" and "e" left out: they start ordinary speech
# ("ih, esqueci", "e aí?"). Speech for others: 11 of 11 ignored, including "pai", "piada", "pássaro".
PI_VARIANTS = ("pi", "pii", "p i", "pi pi", "p")

# In a room with people talking, one recording often holds the end of someone else's speech before
# the call ("Fazer não funciona mais, tá bom? Pi, o que você tá fazendo?", seen in the app): the name
# counts at the start of any sentence, not only of the whole text.
_SENTENCE_START = re.compile(r"[.!?…]\s+")


def _called_at(words: list[str], names: list[str]) -> str | None:
    plain = [normalize(w) for w in words]
    for name in names:
        said = ""
        for i, word in enumerate(plain):
            said = f"{said} {word}".strip()
            if said == name:
                return " ".join(words[i + 1:]).lstrip(",.!?;: ").strip()
            if not name.startswith(said):
                break
    return None


def hotwords(assistant_name: str) -> str:
    """The names Whisper should expect at the start of a call. Measured on the same audio (2026-11-09,
    noisy room): calls recognized 15/18 with the hint vs 11/18 without ("Pio", "Vi", "B." became "PI");
    speech for others still 21/21 ignored, "pai", "pia" and "piada" included. Only while "Só com PI"
    is on: the hint also bends ordinary words ("Que horas são?" came out "Quero ação!")."""
    custom = (assistant_name or "").strip()
    return "PI" if not custom or normalize(custom) in ("pi", "pi dreams") else f"PI, {custom}"


def strip_name(text: str, assistant_name: str) -> str | None:
    """The request after the name when a sentence starts with it; "" for the name alone; None
    when no sentence starts with the name (the speech was not for the assistant)."""
    names = sorted({*PI_VARIANTS, normalize(assistant_name or "")} - {""}, key=len, reverse=True)
    starts = [0] + [m.end() for m in _SENTENCE_START.finditer(text)]
    for start in starts:
        request = _called_at(text[start:].split(), names)
        if request is not None:
            return request
    return None
