"""Audio devices stored by NAME.

sounddevice's index changes when a device is plugged in or removed; the name does
not. Only Windows' default audio API is listed — the others (DirectSound,
WASAPI...) repeat the same devices with other indexes.
"""

import logging

import sounddevice as sd

log = logging.getLogger(__name__)

_CHANNELS = {"input": "max_input_channels", "output": "max_output_channels"}


def _default_host() -> int:
    try:
        return sd.query_devices(sd.default.device[0])["hostapi"]
    except Exception:
        return 0


def list_items(kind: str) -> list[str]:
    """Names of the input ('input') or output ('output') devices."""
    try:
        devices_found = sd.query_devices()
    except Exception:
        return []
    host = _default_host()
    names = []
    for d in devices_found:
        if d["hostapi"] == host and d[_CHANNELS[kind]] > 0 and d["name"] not in names:
            names.append(d["name"])
    return names


def index(name: str | None, kind: str) -> int | None:
    """Current index of the device; None = Windows default (also when it is gone)."""
    if not name:
        return None
    try:
        devices_found = sd.query_devices()
    except Exception:
        return None
    host = _default_host()
    for i, d in enumerate(devices_found):
        if d["name"] == name and d["hostapi"] == host and d[_CHANNELS[kind]] > 0:
            return i
    log.warning("Audio device '%s' not found; using the Windows default", name)
    return None
