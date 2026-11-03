"""Actions on the PC: volume and media, open windows, brightness, lock and shutdown.

Tools follow reminders.py: clear names and few arguments (one tool with an "acao" field made
qwen2.5:14b call it with no arguments in a loop). Sensitive ones — closing an app, locking,
shutting down, restarting — go through the same confirmation as the MCP connections.
"""

import datetime as dt
import re
from typing import Callable

from pidreams.pc import audio, system, windows

STEP = 10                              # volume and brightness step, in points
_DEFAULT_SHUTDOWN_S = 60
_MAX_SHUTDOWN_MIN = 24 * 60

# Asks the person for a "sim"; set by tools.configure_mcp (this module cannot import tools).
_CONFIRM: list[Callable[[str], bool]] = [lambda _action: False]


def configure(confirm: Callable[[str], bool]) -> None:
    _CONFIRM[0] = confirm


def _confirmed(action: str) -> bool:
    """action completes "Posso fazer isto: …?" (e.g. "fechar o Bloco de Notas")."""
    return bool(_CONFIRM[0](action))


_CANCELLED = "Cancelado pelo usuário: nada foi feito."


def _target(current: int, valor, direcao) -> tuple[int, bool]:
    """New level from a value or a direction, kept in 0–100. Returns (level, was_limited)."""
    if valor not in (None, ""):
        wanted = int(round(float(valor)))
    elif str(direcao).lower() in ("mais", "menos"):
        wanted = current + (STEP if str(direcao).lower() == "mais" else -STEP)
    else:
        raise ValueError("diga um valor de 0 a 100 ou a direção 'mais' ou 'menos'")
    level = max(0, min(100, wanted))
    return level, level != wanted


def _as_bool(value) -> bool:
    return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "sim", "yes")


# ── volume and media ─────────────────────────────────────────────────────────

def mudar_volume(valor=None, direcao=None) -> str:
    try:
        level, limited = _target(audio.get_volume(), valor, direcao)
    except ValueError as e:
        return f"[Erro] {e}."
    audio.set_volume(level)
    if level > 0 and audio.get_mute():
        audio.set_mute(False)             # "aumenta o volume" with the sound muted means: I want sound
    edge = " (é o máximo)" if limited and level == 100 else " (é o mínimo)" if limited else ""
    return f"Volume em {level}%{edge}."


def silenciar(mudo=True) -> str:
    muted = _as_bool(mudo)
    audio.set_mute(muted)
    return "Som mudo." if muted else f"Som de volta, em {audio.get_volume()}%."


_MEDIA = {"pausar": ("play_pause", "pausar"), "continuar": ("play_pause", "continuar"),
          "proxima": ("next", "passar para a próxima"), "anterior": ("previous", "voltar para a anterior")}


def controlar_musica(comando: str) -> str:
    key = _MEDIA.get(windows._plain(comando).replace(" ", "").replace("faixa", ""))
    if key is None:
        return "[Erro] comando deve ser 'pausar', 'continuar', 'proxima' ou 'anterior'."
    audio.media_key(key[0])
    # The effect cannot be checked: say what was sent, not "pausei".
    return f"Mandei {key[1]} o que está tocando."


# ── windows ──────────────────────────────────────────────────────────────────

def ver_janelas() -> str:
    counts: dict[str, int] = {}
    for w in windows.list_windows():
        counts[w.name] = counts.get(w.name, 0) + 1
    if not counts:
        return "Nenhum app aberto além do PI dreams."
    items = [f"{name} ({n} janelas)" if n > 1 else name for name, n in counts.items()]
    return "Abertos: " + ", ".join(items) + "."


def _is_pi(app: str) -> bool:
    plain = windows._plain(app)
    return "pi" in plain.replace("-", " ").split() or "dream" in plain


def _not_open(app: str) -> str:
    if _is_pi(app):
        return "Essa é a minha própria janela: não mexo nela por aqui (o botão Encerrar me fecha)."
    return f"Não achei '{app}' aberto. Quer que eu abra?"


def mexer_janela(app: str, como: str = "frente") -> str:
    found = windows.match(windows.list_windows(), app)
    if not found:
        return _not_open(app)
    how = windows._plain(como)
    if how.startswith("mini"):
        for w in found:
            windows.minimize(w)
        return f"{found[0].name} minimizado."
    if how.startswith("maxi"):
        for w in found:
            windows.maximize(w)
        return f"{found[0].name} maximizado."
    windows.bring_to_front(found[0])     # the most recently used one (top of the stack)
    extra = f" (há {len(found)} janelas; trouxe a usada por último)" if len(found) > 1 else ""
    return f"{found[0].name} em primeiro plano{extra}."


def minimizar_tudo() -> str:
    windows.minimize_all()
    return "Janelas minimizadas."


def fechar_app(app: str) -> str:
    found = windows.match(windows.list_windows(), app)
    if not found:
        return _not_open(app)
    name = found[0].name
    what = f"as {len(found)} janelas do {name}" if len(found) > 1 else f"o {name}"
    if not _confirmed(f"fechar {what}"):
        return _CANCELLED
    for w in found:
        windows.close(w)
    return f"Pedi para fechar {what} (se houver algo sem salvar, ele pergunta)."


# ── system ───────────────────────────────────────────────────────────────────

def mudar_brilho(valor=None, direcao=None) -> str:
    current = system.get_brightness()
    if current is None:
        return "Esta tela não aceita ajuste de brilho pelo PC."
    try:
        level, limited = _target(current, valor, direcao)
    except ValueError as e:
        return f"[Erro] {e}."
    done = system.set_brightness(level)
    if not done:
        return "Esta tela não aceita ajuste de brilho pelo PC."
    screens = f" nas {done} telas" if done > 1 else ""
    return f"Brilho em {level}%{screens}." + (" (é o limite)" if limited else "")


# Shutdown/restart scheduled by PI: (mode, deadline). Cancelling must not depend on the model
# choosing a tool — on 2026-11-01 "Cancela o desligamento! Cancela!" got no tool call and the PC
# shut down. While one is pending, the agent loop and the window cancel it by code.
_PENDING: list[tuple[str, dt.datetime] | None] = [None]
# "para" alone is also a preposition ("volume para 30"): only "para o/de desligar" counts.
_CANCEL_WORDS = re.compile(r"\b(cancel\w*|pare\b|aborta\w*|desist\w*|n[aã]o (deslig|reinici)\w*"
                           r"|para (o |de )?(deslig|reinici)\w*)", re.IGNORECASE)


def pending_shutdown() -> tuple[str, dt.datetime] | None:
    pending = _PENDING[0]
    if pending and pending[1] < dt.datetime.now():
        _PENDING[0] = pending = None           # time is up: nothing left to cancel
    return pending


def is_cancel_request(text: str) -> bool:
    return bool(_CANCEL_WORDS.search(text or ""))


def cancelar_desligamento() -> str:
    _PENDING[0] = None
    return "Desligamento cancelado." if system.cancel_shutdown() else "Não havia desligamento agendado."


def bloquear_pc() -> str:
    if not _confirmed("bloquear o PC"):
        return _CANCELLED
    system.lock()
    return "PC bloqueado."


def _schedule(mode: str, minutos) -> str:
    try:
        seconds = _DEFAULT_SHUTDOWN_S if minutos in (None, "", 0) else round(float(minutos) * 60)
    except (TypeError, ValueError):
        return "[Erro] minutos deve ser um número."
    if not 0 < seconds <= _MAX_SHUTDOWN_MIN * 60:
        return "[Erro] o prazo vai de alguns segundos a 24 horas."
    when = "em 1 minuto" if seconds == 60 else f"em {seconds // 60} minutos" if seconds >= 120 else f"em {seconds} s"
    if not _confirmed(f"{mode} o PC {when}"):
        return _CANCELLED
    system.schedule(mode, seconds)
    deadline = dt.datetime.now() + dt.timedelta(seconds=seconds)
    _PENDING[0] = (mode, deadline)
    at = deadline.strftime("%H:%M")
    verb = "desliga" if mode == "desligar" else "reinicia"
    return f"O PC {verb} às {at}. Diga \"cancela o desligamento\" para parar."


def desligar_pc(minutos=None) -> str:
    return _schedule("desligar", minutos)


def reiniciar_pc(minutos=None) -> str:
    return _schedule("reiniciar", minutos)


# ── schemas ──────────────────────────────────────────────────────────────────

def _schema(name: str, description: str, properties: dict, required: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


_LEVEL = {"valor": {"type": "integer", "description": "Número de 0 a 100, quando o usuário disser um valor."},
          "direcao": {"type": "string", "enum": ["mais", "menos"],
                      "description": "Use quando ele pedir para aumentar ('mais') ou diminuir ('menos') sem dizer o valor."}}

_MINUTES = {"minutos": {"type": "number", "description": (
    "Daqui a quantos minutos, se o usuário disser ('daqui a 10 minutos' → 10; 'em meia hora' → 30).")}}

SCHEMAS = [
    _schema("mudar_volume", "Muda o volume do computador: aumentar, abaixar ou pôr num valor ('volume em 30').",
            _LEVEL, []),
    _schema("silenciar", "Deixa o som do computador mudo ou tira do mudo ('muta', 'desmuta', 'tira o som').",
            {"mudo": {"type": "boolean", "description": "true para mutar, false para o som voltar."}}, ["mudo"]),
    _schema("controlar_musica", "Pausa, continua, passa para a próxima ou volta para a anterior a música ou o vídeo "
            "que está tocando no computador (Spotify, YouTube etc.).",
            {"comando": {"type": "string", "enum": ["pausar", "continuar", "proxima", "anterior"]}}, ["comando"]),
    _schema("ver_janelas", "Diz quais programas e janelas estão abertos no computador agora.", {}, []),
    _schema("mexer_janela", "Traz um programa já aberto para a frente, minimiza ou maximiza a janela dele.",
            {"app": {"type": "string", "description": "Nome do programa (ex.: 'Chrome', 'Bloco de Notas')."},
             "como": {"type": "string", "enum": ["frente", "minimizar", "maximizar"]}}, ["app", "como"]),
    _schema("minimizar_tudo", "Minimiza todas as janelas e mostra a área de trabalho.", {}, []),
    # No "pergunta antes" in descriptions: with it the model asked by itself instead of calling the
    # tool (measured); the confirmation is enforced by code anyway.
    _schema("fechar_app", "Fecha um programa aberto no computador.",
            {"app": {"type": "string", "description": "Nome do programa a fechar."}}, ["app"]),
    _schema("mudar_brilho", "Muda o brilho da tela: aumentar, diminuir ou pôr num valor ('brilho em 40').",
            _LEVEL, []),
    # One tool per power action: with a "modo" field qwen2.5:14b left it empty in 6 of 10 cases
    # (measured 2026-11-01), the same failure the reminders showed with "acao".
    _schema("bloquear_pc", "Bloqueia o computador (vai para a tela de bloqueio).", {}, []),
    _schema("desligar_pc", "Desliga o computador, agora ou daqui a alguns minutos.", _MINUTES, []),
    _schema("reiniciar_pc", "Reinicia o computador, agora ou daqui a alguns minutos.", _MINUTES, []),
    _schema("cancelar_desligamento", "Cancela um desligamento ou reinício do computador que estava agendado.", {}, []),
]

FUNCTIONS = {
    "mudar_volume": mudar_volume, "silenciar": silenciar, "controlar_musica": controlar_musica,
    "ver_janelas": ver_janelas, "mexer_janela": mexer_janela, "minimizar_tudo": minimizar_tudo,
    "fechar_app": fechar_app, "mudar_brilho": mudar_brilho, "bloquear_pc": bloquear_pc,
    "desligar_pc": desligar_pc, "reiniciar_pc": reiniciar_pc, "cancelar_desligamento": cancelar_desligamento,
}
