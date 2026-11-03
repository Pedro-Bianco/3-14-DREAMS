"""Failures become notices with actions, never an endless "loading".

The agent loop does not give up when something fails: it emits a problem (code,
message, actions), the window shows a bar with buttons, and the loop checks again
every few seconds until it is solved — and then carries on by itself.
Actions are names; the window runs them (ui/main_window.py).
"""

import asyncio
import logging
import winreg

from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)

INTERVAL_S = 3.0     # between checks; diagnosing takes up to ~3 s → notice in < 15 s

_OLLAMA = {
    "missing": ("O Ollama não está instalado — é ele que roda os modelos de IA.",
                [("BAIXAR O OLLAMA", "ollama_site")]),
    "stopped": ("O Ollama está fechado e não conseguiu iniciar.", [("INICIAR", "ollama_start")]),
    "stuck": ("O Ollama está aberto, mas não responde.", [("REINICIAR O OLLAMA", "ollama_restart")]),
    "port_busy": ("Outro programa ocupa a porta do Ollama: {owner}. Feche esse programa.",
                      [("ABRIR LOG", "open_log")]),
}


def problem(code: str, message: str, actions: list[tuple[str, str]], level: str = "error") -> dict:
    return {"code": code, "msg": message, "actions": actions, "level": level}


async def _wait_for(stop: asyncio.Event | None) -> bool:
    """Sleeps one interval; True if asked to shut down."""
    for _ in range(int(INTERVAL_S / 0.25)):
        if stop and stop.is_set():
            return True
        await asyncio.sleep(0.25)
    return False


async def wait_for_ollama(emit, stop=None) -> bool:
    """Blocks until Ollama answers (notifying meanwhile). False = shut down."""
    from pidreams.hardware import ollama_supervisor

    notified = None
    while True:
        d = await asyncio.to_thread(ollama_supervisor.ensure)
        if d.state == "ok":
            if notified:
                emit("resolved", "ollama")
            return True
        if d.state != notified:
            msg, actions = _OLLAMA[d.state]
            emit("problem", problem("ollama", msg.format(owner=d.owner), actions))
            log.warning("Ollama: %s", d.state)
            notified = d.state
        if await _wait_for(stop):
            return False


async def wait_for_model(emit, stop=None) -> bool:
    from pidreams.hardware import models

    notified = False
    while True:
        try:
            present = await asyncio.to_thread(models.ollama_model_present, CONFIG.ollama_model)
        except Exception:
            present = False
        if present:
            if notified:
                emit("resolved", "model")
            return True
        if not notified:
            emit("problem", problem("model", f"O modelo de conversa {CONFIG.ollama_model} não está baixado.",
                                     [("BAIXAR", "download_model")]))
            notified = True
        if await _wait_for(stop):
            return False


def from_chat(error: Exception) -> dict:
    """Failure during a reply: explains it and offers to try again."""
    text = str(error).lower()
    if "not found" in text:
        return problem("chat", f"O modelo {CONFIG.ollama_model} sumiu do Ollama.",
                        [("BAIXAR", "download_model"), ("TENTAR DE NOVO", "retry")])
    if isinstance(error, (ConnectionError, TimeoutError)) or "timed out" in text or "connect" in text:
        return problem("chat", "O Ollama não respondeu a tempo.",
                        [("REINICIAR O OLLAMA", "ollama_restart"), ("TENTAR DE NOVO", "retry")])
    return problem("chat", f"Não consegui responder: {error}", [("TENTAR DE NOVO", "retry")])


def _denied(resource: str) -> bool:
    """Windows privacy settings: global or desktop-app access denied."""
    base = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{resource}"
    for key in (base, base + r"\NonPackaged"):
        try:
            if winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key), "Value")[0] == "Deny":
                return True
        except OSError:
            pass
    return False


def from_microphone(error: Exception) -> dict:
    if _denied("microphone"):
        return problem("microphone", "O Windows está bloqueando o microfone para aplicativos.",
                        [("ABRIR PRIVACIDADE", "microphone_privacy")])
    return problem("microphone", f"Não consegui usar o microfone ({error}). Usando o padrão do Windows.",
                    [], level="warning")


def from_camera(error: Exception) -> dict:
    if _denied("webcam"):
        return problem("camera", "O Windows está bloqueando a câmera para aplicativos.",
                        [("ABRIR PRIVACIDADE", "camera_privacy")])
    return problem("camera", f"Nenhuma câmera disponível ({error}).", [], level="warning")
