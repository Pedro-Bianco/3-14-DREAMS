"""Secrets (API keys, passwords, private links) encrypted by Windows itself.

DPAPI (CryptProtectData) ties the content to the Windows user: another user on the
same machine, or a copy of the file on another PC, cannot read it. Values never go
to the log or to settings.json.
"""

import ctypes
import json
import logging
import os
from ctypes import wintypes

from pidreams.core import paths

log = logging.getLogger(__name__)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _call(function, data: bytes) -> bytes:
    entry, output = _blob(data), _Blob()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x1: never open a dialog
    if not function(ctypes.byref(entry), None, None, None, None, 0x1, ctypes.byref(output)):
        raise OSError(ctypes.get_last_error(), "DPAPI failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _encrypt(data: bytes) -> bytes:
    return _call(ctypes.windll.crypt32.CryptProtectData, data)


def _decrypt(data: bytes) -> bytes:
    return _call(ctypes.windll.crypt32.CryptUnprotectData, data)


def _read() -> dict[str, str]:
    file = paths.secrets_file()
    if not file.is_file():
        return {}
    try:
        return json.loads(_decrypt(file.read_bytes()).decode("utf-8"))
    except (OSError, ValueError):
        log.warning("secrets.bin unreadable (another Windows user or a corrupted file)")
        return {}


def _write(secrets_map: dict[str, str]) -> None:
    file = paths.secrets_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file.with_suffix(".bin.tmp")
    temp_file.write_bytes(_encrypt(json.dumps(secrets_map).encode("utf-8")))
    os.replace(temp_file, file)


def get(key: str) -> str | None:
    return _read().get(key)


def set(key: str, value: str) -> None:  # noqa: A001 — short, explicit API: secrets.set
    secrets_map = _read()
    secrets_map[key] = value
    _write(secrets_map)


def delete(key: str) -> None:
    secrets_map = _read()
    if secrets_map.pop(key, None) is not None:
        _write(secrets_map)
