"""Hardware profile: which GPU exists and how much video memory it has.

Source: the display adapter class in the Windows registry. VRAM comes from
HardwareInformation.qwMemorySize (64 bits) — Win32_VideoController.AdapterRAM
is 32 bits and would report 4 GB for a 12 GB card. This is the only module that
knows GPU vendors.
"""

import functools
import json
import logging
import winreg
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import psutil

from pidreams.core import paths

log = logging.getLogger(__name__)

_VIDEO_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_FIELDS = ("MatchingDeviceId", "DriverDesc", "DriverVersion", "HardwareInformation.qwMemorySize")
_VENDORS = {"10DE": "nvidia", "8086": "intel", "1002": "amd"}
# Below this it is an integrated card: dedicated memory too small for an LLM.
MIN_VRAM = 2 * 1024**3


@dataclass
class HardwareProfile:
    backend_detected: str                    # "nvidia" | "vulkan" | "cpu"
    gpu_name: str | None
    vendor: str | None                       # "nvidia" | "intel" | "amd" | None
    vram_bytes: int | None
    driver_version: str | None
    ram_bytes: int
    ollama_backend: str | None = None        # confirmed by Ollama's server.log
    ollama_gpu_name: str | None = None
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def vram_gb(self) -> float:
        return (self.vram_bytes or 0) / 1024**3

    @property
    def diverges(self) -> bool:
        """GPU detected by Windows, but Ollama runs on something else (e.g. CPU)."""
        if not self.ollama_backend:
            return False
        expected = {"nvidia": "cuda", "vulkan": "vulkan", "cpu": "cpu"}[self.backend_detected]
        return self.ollama_backend.lower() != expected


def read_registry() -> list[dict]:
    adapters = []
    try:
        class_name = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _VIDEO_CLASS)
    except OSError:
        return adapters
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(class_name, i)
        except OSError:
            break
        i += 1
        if not sub.isdigit():
            continue
        try:
            key = winreg.OpenKey(class_name, sub)
        except OSError:
            continue
        data = {}
        for name in _FIELDS:
            try:
                data[name] = winreg.QueryValueEx(key, name)[0]
            except OSError:
                pass
        adapters.append(data)
    return adapters


def _vendor(adapter: dict) -> str | None:
    device = str(adapter.get("MatchingDeviceId", "")).upper()
    for code, name in _VENDORS.items():
        if f"VEN_{code}" in device:
            return name
    return None


def detect(adapters: list[dict] | None = None, ram_bytes: int | None = None) -> HardwareProfile:
    adapters = read_registry() if adapters is None else adapters
    ram = psutil.virtual_memory().total if ram_bytes is None else ram_bytes
    candidates = [a for a in adapters
                  if _vendor(a) and int(a.get("HardwareInformation.qwMemorySize") or 0) >= MIN_VRAM]
    if not candidates:
        return HardwareProfile("cpu", None, None, None, None, ram)
    best = max(candidates, key=lambda a: int(a["HardwareInformation.qwMemorySize"]))
    vendor = _vendor(best)
    return HardwareProfile(
        backend_detected="nvidia" if vendor == "nvidia" else "vulkan",
        gpu_name=best.get("DriverDesc"),
        vendor=vendor,
        vram_bytes=int(best["HardwareInformation.qwMemorySize"]),
        driver_version=best.get("DriverVersion"),
        ram_bytes=ram,
    )


def save(profile: HardwareProfile) -> None:
    file = paths.user_data_dir() / "hardware.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8")


def load() -> HardwareProfile | None:
    file = paths.user_data_dir() / "hardware.json"
    try:
        return HardwareProfile(**json.loads(file.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


@functools.lru_cache(maxsize=1)
def current_profile() -> HardwareProfile:
    """Detected once per run (the model is looked up on every message)."""
    profile = detect()
    log.info("Hardware: %s, %s, %.0f GB of VRAM", profile.backend_detected, profile.gpu_name or "no GPU",
             profile.vram_gb)
    return profile


def redetect() -> HardwareProfile:
    current_profile.cache_clear()
    return current_profile()
