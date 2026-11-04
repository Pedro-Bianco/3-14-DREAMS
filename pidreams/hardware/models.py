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


# ── Voice files: fixed files with known sizes, downloaded straight from their release ──

def _files_present(kind: str, files: dict[str, tuple[str, int]]) -> bool:
    folder = paths.models_dir(kind)
    return all((folder / name).is_file() and (folder / name).stat().st_size == size
               for name, (_url, size) in files.items())


def _download_files(label: str, kind: str, files: dict[str, tuple[str, int]],
                    progress: Progress, cancel: threading.Event) -> None:
    """files: {local name: (url, size in bytes)}. A half file never sits under the real name."""
    import urllib.request

    from pidreams import USER_AGENT

    folder = paths.models_dir(kind)
    if _files_present(kind, files):
        progress(100, f"{label} já instaladas")
        return
    total = sum(size for _url, size in files.values())
    check_space(folder, total)
    done = 0
    for name, (url, size) in files.items():
        target = folder / name
        if target.is_file() and target.stat().st_size == size:
            done += size
            continue
        part = target.with_suffix(target.suffix + ".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response, open(part, "wb") as out:
                while chunk := response.read(1024 * 1024):
                    if cancel.is_set():
                        raise Cancelled()
                    out.write(chunk)
                    done += len(chunk)
                    progress(min(99.0, 100 * done / total), f"{label}: {done / 1024**2:.0f} de {total / 1024**2:.0f} MB")
        except Cancelled:
            part.unlink(missing_ok=True)
            raise
        except Exception as e:
            part.unlink(missing_ok=True)
            raise DownloadFailed(f"Não foi possível baixar as {label.lower()} ({name}): {e}") from e
        if part.stat().st_size != size:
            part.unlink(missing_ok=True)
            raise DownloadFailed(f"O arquivo {name} das {label.lower()} chegou incompleto. Tente de novo.")
        part.replace(target)
    progress(100, f"{label} prontas")


# Kokoro voices (GitHub release of kokoro-onnx; Kokoro-82M weights, Apache-2.0). Sizes of the release
# files (2026-11-04); the full-precision model is the one chosen by ear. Optional voices: downloaded
# when one is chosen in the settings.
_KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
_KOKORO_FILES = {name: (_KOKORO_URL + name, size) for name, size in
                 {"kokoro-v1.0.onnx": 325_505_369, "voices-v1.0.bin": 28_214_398}.items()}


def kokoro_present() -> bool:
    return _files_present("kokoro", _KOKORO_FILES)


def download_kokoro(progress: Progress, cancel: threading.Event) -> None:
    _download_files("Vozes Kokoro", "kokoro", _KOKORO_FILES, progress, cancel)


# Pocket TTS, Portuguese (Kyutai, CC-BY-4.0): the public weights, without voice cloning, pinned to
# the revisions pocket-tts 4.0.1 names. The default voice is a state file shipped with the app.
_POCKET_REPO = "https://huggingface.co/kyutai/pocket-tts-without-voice-cloning/resolve/"
POCKET_FILES = {
    "model.safetensors": (_POCKET_REPO + "1e08e6a23401048648a9fdcfde2f89348215c2a7/languages/portuguese/model.safetensors",
                          219_029_196),
    "tokenizer.json": (_POCKET_REPO + "4e1e0a3e611c51c0b4ed8174fc10f32a54644303/languages/portuguese/tokenizer.json",
                       247_014),
}


def pocket_present() -> bool:
    return _files_present("pocket", POCKET_FILES)


def download_pocket(progress: Progress, cancel: threading.Event) -> None:
    _download_files("Vozes", "pocket", POCKET_FILES, progress, cancel)


# ── Conjuntos ─────────────────────────────────────────────────────────────────

def essentials() -> list[tuple[str, Callable[[Progress, threading.Event], None]]]:
    """What the install downloads: chatting by voice needs these four. The deep research's stronger
    model is optional (Configurações → Hardware)."""
    return [
        (f"Modelo de conversa ({CONFIG.ollama_model})", lambda p, c: download_ollama(CONFIG.ollama_model, p, c)),
        ("Reconhecimento de voz (Whisper)", download_whisper),
        ("Memória (embeddings)", download_embeddings),
        ("Voz (~210 MB)", download_pocket),
    ]
