"""Ollama supervisor: is it installed? does it answer? who holds the port?

Starts only the SERVER, hidden (`ollama serve`): opening "ollama app.exe" would show
Ollama 0.40's catalog window to every user. The server output goes to
logs/ollama_serve.log — that is where we read which GPU it is using.
"""

import json
import logging
import os
import re
import subprocess
import time
import urllib.request
import winreg
from dataclasses import dataclass
from pathlib import Path

import psutil

from pidreams.core import paths
from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)

PORT = 11434
_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{44E83376-CE68-45EB-8FC1-393500EB558C}_is1"
_NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW


@dataclass
class Diagnosis:
    state: str                    # ok | ausente | parado | travado | porta_ocupada
    version: str | None = None
    owner: str | None = None        # executable holding the port, when it is not the official Ollama


# ── where Ollama is ──────────────────────────────────────────────────────────

def install_folder() -> Path:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY)
        return Path(winreg.QueryValueEx(key, "InstallLocation")[0])
    except OSError:
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"


def executable_path() -> Path:
    return install_folder() / "ollama.exe"


def is_official(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve().parent == install_folder().resolve()
    except OSError:
        return False


def server_log() -> Path:
    """Ours, if we started it; otherwise the Ollama app's."""
    ours = paths.logs_dir() / "ollama_serve.log"
    if ours.is_file() and ours.stat().st_size:
        return ours
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"


# ── estado ───────────────────────────────────────────────────────────────────

def version(timeout: float = 3.0) -> str | None:
    try:
        with urllib.request.urlopen(f"{CONFIG.ollama_host}/api/version", timeout=timeout) as r:
            return json.loads(r.read()).get("version")
    except Exception:
        return None


def port_owner() -> tuple[int, str | None] | None:
    try:
        connections = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied:
        return None
    for c in connections:
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == PORT and c.pid:
            try:
                return c.pid, psutil.Process(c.pid).exe()
            except psutil.Error:
                return c.pid, None
    return None


def diagnose() -> Diagnosis:
    owner = port_owner()
    if owner is None:
        return Diagnosis("stopped" if executable_path().is_file() else "missing")
    _, path = owner
    if path and not is_official(path):
        return Diagnosis("port_busy", owner=path)
    v = version()
    return Diagnosis("ok", version=v) if v else Diagnosis("stuck")


# ── actions ──────────────────────────────────────────────────────────────────

def start(wait_s: float = 40.0) -> bool:
    exe = executable_path()
    if not exe.is_file():
        return False
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    output = open(paths.logs_dir() / "ollama_serve.log", "w", encoding="utf-8")
    subprocess.Popen([str(exe), "serve"], stdout=output, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW, close_fds=True)
    end = time.time() + wait_s
    while time.time() < end:
        if version(timeout=2):
            log.info("Ollama started (hidden server)")
            return True
        time.sleep(0.5)
    return False


def restart() -> bool:
    """Only kills the official Ollama; another program on the port is the user's call."""
    owner = port_owner()
    if owner:
        pid, path = owner
        if path and not is_official(path):
            return False
        try:
            process = psutil.Process(pid)
            for child in process.children(recursive=True):
                child.kill()
            process.kill()
            psutil.wait_procs([process], timeout=10)
        except psutil.Error:
            pass
    return start()


def ensure() -> Diagnosis:
    """Leaves Ollama answering when possible; returns the final diagnosis."""
    d = diagnose()
    if d.state == "stopped":
        start()
        d = diagnose()
    return d


# ── which GPU Ollama is using ────────────────────────────────────────────────

_PAIR = re.compile(r'(\w+)=("[^"]*"|\S+)')


def parse_inference_compute(text: str) -> list[dict]:
    """Devices from the server's LAST startup in the log."""
    blocks = text.split('msg="server config"')
    last_item = blocks[-1] if len(blocks) > 1 else text
    devices = []
    for line in last_item.splitlines():
        if 'msg="inference compute"' in line:
            devices.append({k: v.strip('"') for k, v in _PAIR.findall(line)})
    return devices


def backend_in_use() -> tuple[str, str] | None:
    """(library, description) do primeiro dispositivo, ex.: ("Vulkan", "Intel(R) Arc(TM) B580")."""
    try:
        text = server_log().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    devices = parse_inference_compute(text)
    if not devices:
        return None
    d = devices[0]
    return d.get("library", "cpu"), d.get("description", "")
