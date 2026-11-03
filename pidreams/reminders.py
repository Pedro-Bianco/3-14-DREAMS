"""PI reminders: stored on the PC and announced on open or, with the app open, on time.

Three simple tools. The date comes as the person said it
and `core.dates` does the math. Nothing here asks for confirmation: it only touches the app's own data.
"""

import datetime as dt
import json
import os
import threading
import unicodedata

from pidreams.core import paths
from pidreams.core.dates import InvalidDate, resolve_when
from pidreams.core.text import date_in_words

_LOCK = threading.Lock()

def _schema(name: str, description: str, properties: dict, required_fields: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required_fields}}}


# Three simple tools instead of one with an "acao" field: with the action in a field, qwen2.5:14b
# called the tool with no arguments at all, over and over until the round limit.
SCHEMAS = [
    _schema("criar_lembrete",
            "Guarda um lembrete para o usuário, avisado no dia. Use quando ele pedir para lembrar de algo "
            "('me lembra de…', 'não me deixa esquecer…').",
            {"texto": {"type": "string", "description": "O que lembrar."},
             "quando": {"type": "string", "description": (
                 "As palavras de data e hora EXATAMENTE como o usuário falou ('amanhã', 'sexta', 'dia 12 "
                 "às 15h', 'daqui a 3 dias'). Se ele não disse quando, deixe vazio: não invente.")}},
            ["texto"]),
    _schema("ver_lembretes", "Lista os lembretes pendentes do usuário. Use quando ele perguntar pelos lembretes.",
            {}, []),
    _schema("tirar_lembrete",
            "Tira um lembrete da lista: quando o usuário disser que já fez a coisa lembrada ('já paguei a "
            "conta de luz') ou pedir para apagar um lembrete.",
            {"texto": {"type": "string", "description": "Um trecho do lembrete (ex.: 'conta de luz')."}},
            ["texto"]),
]


def file():
    return paths.user_data_dir() / "lembretes.json"


def _read() -> dict:
    try:
        return json.loads(file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lembretes": [], "ultimo_resumo": ""}


def _write(stored: dict) -> None:
    file().parent.mkdir(parents=True, exist_ok=True)
    temp_file = file().with_suffix(".json.tmp")
    temp_file.write_text(json.dumps(stored, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp_file, file())


def _normalize(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower().strip()


def _when(reminder: dict) -> dt.datetime:
    hour = dt.time.fromisoformat(reminder["hora"]) if reminder.get("hora") else dt.time()
    return dt.datetime.combine(dt.date.fromisoformat(reminder["data"]), hour)


def describe(reminder: dict, now: dt.datetime | None = None) -> str:
    data = dt.date.fromisoformat(reminder["data"])
    texto = f"{reminder['texto']} — {date_in_words(data)}"
    if reminder.get("hora"):
        texto += f", às {reminder['hora'][:5]}"
    if now and data < now.date():
        texto += " (atrasado)"
    return texto


def pending_items() -> list[dict]:
    with _LOCK:
        return sorted((l for l in _read()["lembretes"] if l["estado"] != "concluido"), key=_when)


def due_reminders(now: dt.datetime, only_new: bool = False) -> list[dict]:
    """Pending reminders whose day has come (and time, if any). only_new: not announced yet this time."""
    # Without a time, _when is midnight of the day: it is due as soon as the day arrives.
    return [l for l in pending_items()
            if _when(l) <= now and not (only_new and l["estado"] == "avisado")]


def mark_notified(ids: list[int]) -> None:
    with _LOCK:
        stored = _read()
        for l in stored["lembretes"]:
            if l["id"] in ids and l["estado"] == "pendente":
                l["estado"] = "avisado"
        _write(stored)


def last_briefing() -> str:
    return _read().get("ultimo_resumo", "")


def record_briefing(day: dt.date) -> None:
    with _LOCK:
        stored = _read()
        stored["ultimo_resumo"] = day.isoformat()
        _write(stored)


def create(texto: str, quando: str, now: dt.datetime) -> dict:
    day, hour = resolve_when(quando, now)
    with _LOCK:
        stored = _read()
        reminder = {"id": max((l["id"] for l in stored["lembretes"]), default=0) + 1, "texto": texto.strip(),
                    "data": day.isoformat(), "hora": hour.isoformat(timespec="minutes") if hour else None,
                    "criado": now.isoformat(timespec="seconds"), "estado": "pendente"}
        stored["lembretes"].append(reminder)
        _write(stored)
    return reminder


def _pick(snippet: str) -> tuple[dict | None, str]:
    found = [l for l in pending_items() if _normalize(snippet) and _normalize(snippet) in _normalize(l["texto"])]
    if len(found) == 1:
        return found[0], ""
    if not found:
        return None, f"Não achei lembrete pendente com '{snippet}'."
    return None, "Achei mais de um: " + "; ".join(describe(l) for l in found) + ". Qual deles?"


def criar_lembrete(texto: str, quando: str = "", now: dt.datetime | None = None) -> str:
    if not texto.strip():
        return "Falta o que lembrar."
    if not quando.strip():
        return "Não guardei ainda: pergunte ao usuário quando ele quer ser lembrado (não invente uma data)."
    try:
        reminder = create(texto, quando, now or dt.datetime.now())
    except InvalidDate as e:
        return f"Não guardei: {e} Pergunte de novo ao usuário."
    return f"Guardado: {describe(reminder)}."


def ver_lembretes(now: dt.datetime | None = None) -> str:
    items = pending_items()
    now = now or dt.datetime.now()
    return ("Lembretes pendentes: " + "; ".join(describe(l, now) for l in items) + ".") if items         else "Nenhum lembrete pendente."


def tirar_lembrete(texto: str) -> str:
    """Done and deleted are the same to the person: it leaves the list (kept in the file as done)."""
    reminder, error = _pick(texto)
    if reminder is None:
        return error
    with _LOCK:
        stored = _read()
        for l in stored["lembretes"]:
            if l["id"] == reminder["id"]:
                l["estado"] = "concluido"
        _write(stored)
    return f"Tirado da lista: {reminder['texto']}."


FUNCTIONS = {"criar_lembrete": criar_lembrete, "ver_lembretes": ver_lembretes, "tirar_lembrete": tirar_lembrete}
