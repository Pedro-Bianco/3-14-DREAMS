"""User preferences in %LOCALAPPDATA%\\PIDreams\\settings.json.

Defaults live only here (DEFAULTS). An invalid value never brings the app down: it falls back to
the default and becomes a warning in the log. No migration code until format version 2 exists.
"""

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from pidreams import routines
from pidreams.core import paths

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "first_run_done": False,
    "assistant_name": "PI dreams",
    "treatment": "",
    "persona_id": "espirituoso",
    "appearance": "rosto",       # id from pidreams/ui/appearances (unknown = rosto)
    # startup_sound: the chime played with the startup animation (audio/startup_sound.py).
    "audio": {"input_device": None, "output_device": None, "volume": 1.0, "startup_sound": True},
    # effect: "" = off. wake_name: in voice mode, answer only speech that starts with the name.
    "voice": {"model": "pocket-baritono", "length_scale": 1.0, "effect": "forte", "wake_name": False},
    "weather": {"city": ""},
    "llm": {"model": None},
    "ollama": {"host": "http://127.0.0.1:11434", "timeout_s": 600.0},
    # restrict=False: the agent opens any app asked for. items keeps only the user's
    # choices; the catalog and each app's default live in the APPS tab.
    "apps": {"restrict": False, "items": {}},
    "plugins": {"enabled": [], "config": {}},
    "memory": {"enabled": True, "map_open": True},   # map_open: memory map under the appearance
    # MCP connections: folders allowed for the files server and, per server, whether
    # it is on and how to start it. Stored keys stay in Portuguese (saved format).
    "mcp": {"pastas": [], "servers": {}},
    # Briefing on open: once a day (or every time, with toda_vez), only with the parts that are on
    # and configured.
    "resumo": {"ligado": True, "toda_vez": False, "clima": True, "agenda": True, "emails": True, "lembretes": True},
    # Main window as it was last closed; empty geometry = first opening (centered).
    "window": {"geometry": "", "zoomed": False},
    # Tray: sleep in the notification area instead of closing, wake on two claps, start with
    # Windows; games = executable names that close the app completely when running.
    "tray": {"start_with_windows": False, "close_to_tray": False, "idle_minutes": 10,
             "claps": True, "clap_level": 0.2, "games": [],     # clap_level: from calibrating
             "speak_reminders": True},                           # asleep: speak reminders, not only notify
    # log_speech: write what is said (and answered) to the log, for troubleshooting only.
    "privacy": {"log_speech": False},
    # Speech recognition: "auto" (turbo on an Intel GPU when downloaded, else small), "small", "turbo".
    "stt": {"engine": "auto"},
    # Routines ("protocolos"): pidreams/routines.py; starts with generic examples.
    "routines": copy.deepcopy(routines.EXAMPLES),
}

# Accepted ranges; everything else only needs the default's type.
_RANGES = {
    "audio.volume": (0.0, 1.0),
    "voice.length_scale": (0.5, 2.0),
    "ollama.timeout_s": (10.0, 1800.0),
    "tray.idle_minutes": (1, 240),
    "tray.clap_level": (0.02, 0.5),
}
_LENGTHS = {"assistant_name": (1, 40), "treatment": (0, 40)}
# Fields that take one of a fixed set of values.
_CHOICES = {"voice.effect": {"", "leve", "medio", "forte"}, "stt.engine": {"auto", "small", "turbo"}}
# Fields whose default is None but that accept text.
_TEXT_OR_NULL = {"audio.input_device", "audio.output_device", "llm.model"}
# Free-form dictionaries (keys defined by the user or by plugins).
_FREE_DICTS = {"plugins.config", "apps.items", "mcp.servers"}


def _valid(key: str, value: Any, default: Any) -> bool:
    if key in _TEXT_OR_NULL:
        return value is None or isinstance(value, str)
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, float):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        ok = isinstance(value, type(default))
    if ok and key in _RANGES:
        lo, hi = _RANGES[key]
        ok = lo <= value <= hi
    if ok and key in _LENGTHS:
        lo, hi = _LENGTHS[key]
        ok = lo <= len(value) <= hi
    if ok and key in _CHOICES:
        ok = value in _CHOICES[key]
    if ok and key == "routines":
        ok = all(isinstance(item, dict) for item in value) and routines.problem(value) is None
    elif ok and isinstance(default, list):
        ok = all(isinstance(item, str) for item in value)
    return ok


def _merge(defaults: dict, loaded: dict, prefix: str = "") -> dict:
    """Defaults + valid loaded values; unknown keys are ignored."""
    output = {}
    for key, default in defaults.items():
        path = f"{prefix}{key}"
        if key not in loaded:
            output[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and path not in _FREE_DICTS:
            sub = loaded[key] if isinstance(loaded[key], dict) else {}
            output[key] = _merge(default, sub, path + ".")
        elif path in _FREE_DICTS and isinstance(loaded[key], dict):
            output[key] = loaded[key]
        elif _valid(path, loaded[key], default):
            output[key] = loaded[key]
        else:
            log.warning("settings.json: invalid value at %s (%r); using the default %r",
                        path, loaded[key], default)
            output[key] = copy.deepcopy(default)
    for key in loaded.keys() - defaults.keys():
        log.warning("settings.json: unknown key ignored: %s%s", prefix, key)
    return output


class Settings:
    def __init__(self, file: Path | None = None):
        self._file = file or paths.settings_file()
        self._listeners: list[Callable[["Settings"], None]] = []
        self.data = self._load()

    def _load(self) -> dict:
        loaded: dict = {}
        if self._file.is_file():
            try:
                loaded = json.loads(self._file.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("the content is not a JSON object")
            except (OSError, ValueError) as e:
                log.warning("settings.json unreadable (%s); using the defaults", e)
                loaded = {}
        return _merge(DEFAULTS, loaded)

    def get(self, key: str) -> Any:
        """dotted key, e.g. 'audio.volume'."""
        value: Any = self.data
        for part in key.split("."):
            value = value[part]
        return value

    def set(self, key: str, value: Any) -> None:
        """Same rules as reading the file; invalid value -> ValueError (nothing changes)."""
        default: Any = DEFAULTS
        for part in key.split("."):
            default = default[part] if isinstance(default, dict) else None
        free = key in _FREE_DICTS or any(key.startswith(d + ".") for d in _FREE_DICTS)
        if not free and not isinstance(default, dict) and not _valid(key, value, default):
            raise ValueError(f"invalid value for {key}: {value!r}")
        *path, last = key.split(".")
        target = self.data
        for part in path:
            target = target[part]
        target[last] = value

    def save(self) -> None:
        """Writes atomically (temp file + replace) and notifies the subscribers."""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self._file.with_suffix(".json.tmp")
        temp_file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_file, self._file)
        for listener in list(self._listeners):
            try:
                listener(self)
            except Exception:
                log.exception("error applying a settings change")

    def subscribe(self, listener: Callable[["Settings"], None]) -> None:
        self._listeners.append(listener)


SETTINGS = Settings()
