"""Detecção de hardware e leitura do log do Ollama, com fixtures anonimizadas."""

import json
from pathlib import Path

import pytest

from pidreams.hardware import detect, ollama_supervisor as sup

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RAM = 32 * 1024**3


def _record(name):
    return json.loads((FIXTURES / f"registry_{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name, backend, vendor, vram_gb", [
    ("intel_arc", "vulkan", "intel", 12),
    ("nvidia", "nvidia", "nvidia", 12),
    ("amd", "vulkan", "amd", 8),
    ("cpu_only", "cpu", None, 0),
    ("hybrid_igpu_dgpu", "nvidia", "nvidia", 8),     # dedicada vence a integrada
])
def test_detecta_backend_pelo_registro(name, backend, vendor, vram_gb):
    p = detect.detect(_record(name), RAM)
    assert (p.backend_detected, p.vendor, round(p.vram_gb)) == (backend, vendor, vram_gb)
    assert p.ram_bytes == RAM


@pytest.mark.parametrize("log, library, gpu", [
    ("vulkan", "Vulkan", "Intel(R) Arc(TM) B580 Graphics"),
    ("cuda", "CUDA", "NVIDIA GeForce RTX 3060"),
    ("cpu", "cpu", "cpu"),
])
def test_le_o_dispositivo_da_ultima_inicializacao(log, library, gpu):
    text = (FIXTURES / f"server_log_{log}.log").read_text(encoding="utf-8")
    d = sup.parse_inference_compute(text)[0]
    assert (d["library"], d["description"]) == (library, gpu)


def test_cpu_no_ollama_com_gpu_detectada_e_divergente():
    p = detect.detect(_record("intel_arc"), RAM)
    p.ollama_backend = "cpu"
    assert p.diverges
    p.ollama_backend = "Vulkan"
    assert not p.diverges


def test_diagnostico_porta_ocupada_por_outro_programa(monkeypatch):
    monkeypatch.setattr(sup, "port_owner", lambda: (1234, r"C:\outro\ollama-lib.exe"))
    monkeypatch.setattr(sup, "install_folder", lambda: Path(r"C:\Programas\Ollama"))
    d = sup.diagnose()
    assert d.state == "port_busy" and d.owner.endswith("ollama-lib.exe")


def test_diagnostico_travado_quando_oficial_nao_responde(monkeypatch, tmp_path):
    exe = tmp_path / "ollama.exe"; exe.write_text("")
    monkeypatch.setattr(sup, "install_folder", lambda: tmp_path)
    monkeypatch.setattr(sup, "port_owner", lambda: (1, str(exe)))
    monkeypatch.setattr(sup, "version", lambda timeout=3.0: None)
    assert sup.diagnose().state == "stuck"


def test_diagnostico_parado_e_ausente(monkeypatch, tmp_path):
    monkeypatch.setattr(sup, "port_owner", lambda: None)
    monkeypatch.setattr(sup, "install_folder", lambda: tmp_path)
    assert sup.diagnose().state == "missing"
    (tmp_path / "ollama.exe").write_text("")
    assert sup.diagnose().state == "stopped"
