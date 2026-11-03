"""Where things live — the only place in the code that builds paths.

Two places that never mix:
- install folder: the code and the files shipped with the app (read-only);
- user data folder (%LOCALAPPDATA%\\PIDreams): preferences, memory, secrets, logs
  and downloaded models. The installer never touches it.
"""

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PIDreams"


def install_dir() -> Path:
    """Folder of PIDreams.exe when packaged; repository root during development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_DIR_NAME


def settings_file() -> Path:
    return user_data_dir() / "settings.json"


def secrets_file() -> Path:
    return user_data_dir() / "secrets.bin"


def qdrant_dir() -> Path:
    return user_data_dir() / "data" / "qdrant"


def logs_dir() -> Path:
    return user_data_dir() / "logs"


def models_dir(kind: str) -> Path:
    """kind: piper, embeddings, whisper or cuda."""
    return user_data_dir() / "models" / kind


def cache_dir(kind: str) -> Path:
    """Downloaded data that can be fetched again (monitor: orbits, satellite catalog, radios)."""
    return user_data_dir() / "cache" / kind


def plugin_data_dir(plugin_id: str) -> Path:
    return user_data_dir() / "plugins" / plugin_id


def ensure_dirs() -> None:
    for folder in (qdrant_dir(), logs_dir(), *(models_dir(k) for k in ("piper", "embeddings", "whisper", "cuda"))):
        folder.mkdir(parents=True, exist_ok=True)
