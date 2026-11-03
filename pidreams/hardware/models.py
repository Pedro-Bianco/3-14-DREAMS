"""Makes sure the AI models are downloaded, with progress and cancellation.

Essentials (install): chat model, Whisper and the memory embeddings.
On demand: the vision model, the first time the camera is turned on.
Before downloading, checks the free space and fails with a readable reason.
"""

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Callable

import ollama

from pidreams.core import paths
from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]       # (0–100, texto)

# Sizes measured on 2026-10-16 (used to check the disk before downloading).
_WHISPER_SIZE = 470 * 1024**2
_EMBEDDINGS_SIZE = 2300 * 1024**2
_SLACK = 500 * 1024**2


class DownloadFailed(Exception):
    """Message already in Portuguese, ready to show the user."""


class Cancelled(Exception):
    pass


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


def check_space(folder: Path, needed: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if free < needed + _SLACK:
        unit = folder.drive or str(folder)
        raise DownloadFailed(f"Faltam {_gb(needed + _SLACK - free)} em {unit} para baixar este modelo "
                            f"(precisa de {_gb(needed)}, há {_gb(free)} livres).")


# ── Ollama ────────────────────────────────────────────────────────────────────

def _client_of() -> ollama.Client:
    return ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)


def ensure_ollama() -> None:
    """Leaves the server answering (hidden, without the Ollama window) or explains why not."""
    from pidreams.hardware import ollama_supervisor

    d = ollama_supervisor.ensure()
    messages = {
        "missing": "O Ollama não está instalado. Reinstale o PI dreams ou instale em https://ollama.com/download",
        "stopped": "O Ollama não iniciou. Abra o Ollama pelo menu Iniciar e tente de novo.",
        "stuck": "O Ollama está aberto mas não responde. Feche-o pela bandeja do Windows e tente de novo.",
        "port_busy": f"Outro programa ocupa a porta do Ollama: {d.owner}. Feche-o e tente de novo.",
    }
    if d.state != "ok":
        raise DownloadFailed(messages[d.state])


def ollama_model_present(name: str) -> bool:
    target = name if ":" in name else f"{name}:latest"
    return any(m.model == target for m in _client_of().list().models)


def download_ollama(name: str, progress: Progress, cancel: threading.Event) -> None:
    if ollama_model_present(name):
        progress(100, f"{name} já instalado")
        return
    models_folder = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    checked = False
    try:
        for event in _client_of().pull(name, stream=True):
            if cancel.is_set():
                raise Cancelled()
            if event.total and not checked:
                check_space(models_folder, event.total)
                checked = True
            pct = 100 * (event.completed or 0) / event.total if event.total else 0
            progress(pct, f"{name}: {event.status}")
    except (Cancelled, DownloadFailed):
        raise
    except Exception as e:
        raise DownloadFailed(f"Não foi possível baixar {name}: {e}") from e
    progress(100, f"{name} pronto")


# ── Whisper e embeddings (Hugging Face) ──────────────────────────────────────

def _download_with_wait(label_text: str, size: int, folder: Path, download: Callable[[], None],
                       progress: Progress, cancel: threading.Event) -> None:
    """The libraries expose no progress: it is estimated from the folder size."""
    check_space(folder, size)
    error: list[BaseException] = []
    t = threading.Thread(target=lambda: _capture(download, error), daemon=True)
    initial = _folder_size(folder)
    t.start()
    while t.is_alive():
        if cancel.is_set():
            raise Cancelled()      # the download keeps going in the background until the process exits
        done = _folder_size(folder) - initial
        progress(min(99.0, 100 * done / size), f"{label_text}: baixando")
        t.join(0.5)
    if error:
        raise DownloadFailed(f"Não foi possível baixar {label_text}: {error[0]}") from error[0]
    progress(100, f"{label_text} pronto")


def _capture(function, error: list) -> None:
    try:
        function()
    except BaseException as e:        # noqa: BLE001 — repassado para a thread principal
        error.append(e)


def _folder_size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.exists() else 0


def download_whisper(progress: Progress, cancel: threading.Event) -> None:
    from faster_whisper.utils import download_model

    folder = paths.models_dir("whisper")
    try:
        download_model(CONFIG.whisper_model_size, cache_dir=str(folder), local_files_only=True)
        progress(100, "Whisper já instalado")
        return
    except Exception:
        pass
    _download_with_wait("Whisper", _WHISPER_SIZE, folder,
                       lambda: download_model(CONFIG.whisper_model_size, cache_dir=str(folder)),
                       progress, cancel)


def download_embeddings(progress: Progress, cancel: threading.Event) -> None:
    from pidreams.memory.embedder import FastEmbedManager

    folder = paths.models_dir("embeddings")
    if _folder_size(folder) >= 0.9 * _EMBEDDINGS_SIZE:
        progress(100, "Memória já instalada")
        return
    _download_with_wait("Memória", _EMBEDDINGS_SIZE, folder,
                       lambda: FastEmbedManager(CONFIG.ltm_embedding_model),
                       progress, cancel)


# ── Conjuntos ─────────────────────────────────────────────────────────────────

def essentials() -> list[tuple[str, Callable[[Progress, threading.Event], None]]]:
    """What the install downloads: chatting needs these three."""
    return [
        (f"Modelo de conversa ({CONFIG.ollama_model})", lambda p, c: download_ollama(CONFIG.ollama_model, p, c)),
        ("Reconhecimento de voz (Whisper)", download_whisper),
        ("Memória (embeddings)", download_embeddings),
    ]
