"""Brings an installation with the old layout into the user data folder.

Old layout = everything inside the code folder: data/ (Qdrant memory) and
allowed_apps.json. Runs once; never deletes the source — if anything goes wrong, the
old data stays where it was.
"""

import json
import logging
import os
import shutil
from pathlib import Path

from pidreams.core import paths
from pidreams.core.settings import SETTINGS

log = logging.getLogger(__name__)

_MARKER = "migracao_legado.ok"
# The old layout hardcoded the 14B; whoever migrates keeps it.
_LEGACY_MODEL = "qwen2.5:14b"
# The old prompt always called the user "senhor".
_LEGACY_TREATMENT = "senhor"


def _old_caches() -> list[tuple[Path, Path]]:
    """(old cache, new folder) of models already downloaded outside the data folder."""
    temp = Path(os.environ.get("TEMP", ""))
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    return [
        (temp / "fastembed_cache" / "models--qdrant--multilingual-e5-large-onnx",
         paths.models_dir("embeddings") / "models--qdrant--multilingual-e5-large-onnx"),
        (hub / "models--Systran--faster-whisper-small",
         paths.models_dir("whisper") / "models--Systran--faster-whisper-small"),
    ]


def reuse_caches() -> None:
    """Moves (does not copy) already-downloaded models into the data folder.

    fastembed's default cache lives in %TEMP%, which Disk Cleanup wipes — and the
    download is ~2 GB. Moving on the same disk is instant and does not duplicate.
    """
    for old, new in _old_caches():
        if old.is_dir() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(old), str(new))
                log.info("Model reused: %s → %s", old.name, new.parent)
            except OSError as e:
                log.warning("Could not move %s (%s); it will be downloaded again", old.name, e)


def migrate(source_dir=None) -> bool:
    """Returns True if anything was migrated in this run."""
    source_dir = source_dir or paths.install_dir()
    marker = paths.user_data_dir() / _MARKER
    data, apps = source_dir / "data", source_dir / "allowed_apps.json"
    if marker.exists() or not (data.is_dir() or apps.is_file()):
        return False

    log.info("Old layout found at %s; migrating to %s", source_dir, paths.user_data_dir())
    paths.ensure_dirs()

    if (data / "collection").is_dir() and not any(paths.qdrant_dir().iterdir()):
        shutil.copytree(data, paths.qdrant_dir(), dirs_exist_ok=True)
        log.info("Memory (Qdrant) copied")

    if apps.is_file():
        try:
            old = json.loads(apps.read_text(encoding="utf-8"))
            SETTINGS.set("apps.restrict", bool(old.get("enabled", False)))
            SETTINGS.set("apps.items", {k: bool(v) for k, v in old.get("apps", {}).items()})
        except ValueError:
            log.warning("allowed_apps.json unreadable; keeping the default")

    if not SETTINGS.get("llm.model"):
        SETTINGS.set("llm.model", _LEGACY_MODEL)
    if not SETTINGS.get("treatment"):
        SETTINGS.set("treatment", _LEGACY_TREATMENT)
    SETTINGS.save()
    marker.write_text("ok", encoding="utf-8")
    log.info("Migration finished; the source was not changed")
    return True
