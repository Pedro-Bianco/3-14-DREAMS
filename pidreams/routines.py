"""Routines ("protocolos"): a name and a list of steps the user builds in the settings, started
by a short phrase ("modo trabalho", "protocolo jogo"). The phrase is matched by code, like the
modes, and every step is an action the app already has (open, close with confirmation, volume,
mute, media, say). A failed step does not stop the others; the summary says what failed."""

import logging
import re
import unicodedata
from typing import Callable

log = logging.getLogger(__name__)

STEP_TYPES = ("abrir", "fechar", "volume", "silenciar", "musica", "falar")
MEDIA = ("pausar", "continuar", "proxima", "anterior")
RESERVED = {"monitoramento", "pesquisa", "pesquisa profunda"}     # the existing modes
MAX_STEPS = 20

# How the actions say they did nothing ("Não achei 'x' aberto", "[Erro] ...", "Cancelado ..."),
# compared after normalize().
_FAILED = ("erro", "nao ", "acesso negado", "cancelado", "essa e a minha")

_TRIGGER = re.compile(r"^(?:ativa(?:r)?\s+(?:o\s+|a\s+)?|inicia(?:r)?\s+(?:a\s+|o\s+)?|liga(?:r)?\s+(?:o\s+)?)?"
                      r"(?:modo|protocolo|rotina)\s+(?:de\s+)?(?P<name>.+)$")

EXAMPLES = [
    {"name": "trabalho", "steps": [{"type": "abrir", "value": "code"}, {"type": "musica", "value": "continuar"},
                                   {"type": "volume", "value": "30"}, {"type": "falar", "value": "Bom trabalho."}]},
    {"name": "foco", "steps": [{"type": "musica", "value": "pausar"}, {"type": "silenciar", "value": "sim"},
                               {"type": "falar", "value": "Modo foco ligado. Silenciei o som."}]},
]


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", plain).split())


def problem(routines: list[dict]) -> str | None:
    """What is wrong with the list, in words for the settings screen; None when it is valid."""
    seen = set()
    for routine in routines:
        name = normalize(routine.get("name", ""))
        if not name or len(name) > 30:
            return "cada rotina precisa de um nome de 1 a 30 letras"
        if name in RESERVED:
            return f"o nome \"{routine['name']}\" já é de um modo do PI"
        if name in seen:
            return f"há duas rotinas chamadas \"{routine['name']}\""
        seen.add(name)
        steps = routine.get("steps", [])
        if not 1 <= len(steps) <= MAX_STEPS:
            return f"a rotina \"{routine['name']}\" precisa de 1 a {MAX_STEPS} passos"
        for step in steps:
            kind, value = step.get("type"), str(step.get("value", "")).strip()
            if kind not in STEP_TYPES:
                return f"tipo de passo desconhecido: {kind}"
            if not value:
                return f"um passo \"{kind}\" da rotina \"{routine['name']}\" está sem valor"
            if kind == "volume" and not (value.isdigit() and 0 <= int(value) <= 100):
                return "o volume vai de 0 a 100"
            if kind == "musica" and value not in MEDIA:
                return "música: pausar, continuar, proxima ou anterior"
            if kind == "silenciar" and value not in ("sim", "nao"):
                return "silenciar: sim ou nao"
    return None


def find(text: str, routines: list[dict]) -> dict | None:
    """The routine a short command names ("modo trabalho", "ativar protocolo jogo online"), or None.
    Questions about a routine do not start with the trigger words, so they never match."""
    match = _TRIGGER.match(normalize(text))
    if not match:
        return None
    said = match.group("name")
    by_length = sorted(routines, key=lambda r: -len(normalize(r.get("name", ""))))   # "jogo online" before "jogo"
    return next((r for r in by_length if normalize(r.get("name", "")) == said), None)


def run(routine: dict, actions: dict[str, Callable[[str], str]]) -> str:
    """Runs every step in order (on a worker thread: closing asks for confirmation through the
    microphone) and returns the summary to speak."""
    done, failed = 0, []
    for step in routine["steps"]:
        kind, value = step["type"], str(step["value"])
        try:
            result = actions[kind](value) or ""
        except Exception as e:                      # noqa: BLE001 — one step never stops the others
            log.warning("routine %s, step %s %s: %r", routine["name"], kind, value, e)
            result = f"[Erro] {e}"
        if normalize(result).startswith(_FAILED):
            failed.append(f"{_LABEL[kind]} {value}: {result.removeprefix('[Erro] ').rstrip('.')}")
        else:
            done += 1
    total = len(routine["steps"])
    summary = f"Rotina {routine['name']}: " + ("tudo feito." if not failed else f"{done} de {total} passos feitos.")
    if failed:
        summary += " Não deu: " + "; ".join(failed) + "."
    log.info("routine %s: %d/%d steps", routine["name"], done, total)
    return summary


_LABEL = {"abrir": "abrir", "fechar": "fechar", "volume": "volume", "silenciar": "silenciar",
          "musica": "música", "falar": "falar"}
