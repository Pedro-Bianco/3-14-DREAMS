"""Portable Node and the built-in servers' packages, downloaded only when the person turns on
the first server that needs them: the installer does not grow.

Pinned versions, each published more than two weeks before it was chosen: a third-party update
cannot change behavior or bring in code without going through here.
"""

import hashlib
import json
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path

from pidreams.core import paths
from pidreams.hardware.models import Cancelled, DownloadFailed, Progress, check_space

NODE_VERSION = "24.22.0"          # LTS, 2026-10-14
_NODE_ZIP = f"node-v{NODE_VERSION}-win-x64"
_NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{_NODE_ZIP}.zip"
_NODE_SHA256 = "f9683a19877e12a9b167305c8db71040d812876359de21f0d2e97c3f321f80c3"   # SHASUMS256.txt oficial

PACKAGES = {                      # npm, pinned version
    "@modelcontextprotocol/server-filesystem": "1.0.0",     # 2026-10-11, MIT
    "@playwright/mcp": "0.0.83",                            # 2026-09-28, Apache-2.0
}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def folder() -> Path:
    return paths.user_data_dir() / "runtime"


def node() -> Path:
    return folder() / "node" / "node.exe"


def module(package: str) -> Path:
    """Ponto de entrada do pacote instalado (o `bin` do package.json)."""
    root_dir = folder() / "mcp" / "node_modules" / package
    binary = json.loads((root_dir / "package.json").read_text(encoding="utf-8")).get("bin", {})
    path = binary if isinstance(binary, str) else next(iter(binary.values()))
    return root_dir / path


def is_ready() -> bool:
    return node().is_file() and all((folder() / "mcp" / "node_modules" / p).is_dir() for p in PACKAGES)


def install(progress: Progress, cancel: threading.Event) -> None:
    """For the DownloadDialog: downloads and verifies Node, then installs the packages."""
    if not node().is_file():
        _download_node(progress, cancel)
    if cancel.is_set():
        raise Cancelled()
    _install_packages(progress)
    progress(100, "Conexões prontas")


def _download_node(progress: Progress, cancel: threading.Event) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    zip_ = folder() / f"{_NODE_ZIP}.zip"
    total_sum = hashlib.sha256()
    try:
        with urllib.request.urlopen(_NODE_URL, timeout=30) as resp, open(zip_, "wb") as output:
            total = int(resp.headers.get("Content-Length") or 0)
            if total:
                check_space(folder(), total * 3)            # zip + extracted
            loaded = 0
            while block := resp.read(1 << 16):
                if cancel.is_set():
                    raise Cancelled()
                output.write(block)
                total_sum.update(block)
                loaded += len(block)
                if total:
                    progress(70 * loaded / total, f"Node {NODE_VERSION}: {loaded >> 20} de {total >> 20} MB")
    except (Cancelled, DownloadFailed):
        zip_.unlink(missing_ok=True)
        raise
    except Exception as e:
        zip_.unlink(missing_ok=True)
        raise DownloadFailed(f"Não foi possível baixar o Node: {e}") from e
    if total_sum.hexdigest() != _NODE_SHA256:
        zip_.unlink(missing_ok=True)
        raise DownloadFailed("O Node baixado não confere com a assinatura oficial; nada foi instalado.")
    progress(75, "Extraindo o Node")
    with zipfile.ZipFile(zip_) as z:
        # Long-path prefix: Node's npm has deep folders and, with a long user name, it would
        # go past Windows' 260 characters (seen while testing).
        z.extractall("\\\\?\\" + str(folder().resolve()))
    zip_.unlink()
    shutil.rmtree(folder() / "node", ignore_errors=True)
    (folder() / _NODE_ZIP).rename(folder() / "node")


def _install_packages(progress: Progress) -> None:
    destination = folder() / "mcp"
    destination.mkdir(parents=True, exist_ok=True)
    progress(80, "Instalando os servidores de arquivos e navegador")
    npm = node().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    specs = [f"{p}@{v}" for p, v in PACKAGES.items()]
    result = subprocess.run(
        [str(node()), str(npm), "install", "--prefix", str(destination), "--no-audit", "--no-fund",
         "--save-exact", *specs],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=600)
    if result.returncode != 0:
        raise DownloadFailed("Não foi possível instalar os servidores: " + result.stderr.strip()[-300:])
