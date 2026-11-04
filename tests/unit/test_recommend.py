"""Recomendação de modelos por perfil de hardware."""

import pytest

from pidreams.hardware.detect import HardwareProfile
from pidreams.hardware.recommend import recommend_models

GB = 1024**3


def _profile(backend, vram_gb):
    return HardwareProfile(backend, "placa", None, int(vram_gb * GB) if vram_gb else None, None, 32 * GB)


@pytest.mark.parametrize("backend, vram, llm, stt, swap", [
    ("vulkan", 16, "qwen2.5:14b", "cpu", False),
    ("nvidia", 16, "qwen2.5:14b", "cuda", False),
    ("vulkan", 12, "qwen3:8b", "cpu", False),     # the 14b spilled out of a 12 GB card (2026-11-04)
    ("nvidia", 12, "qwen3:8b", "cuda", False),
    ("nvidia", 8, "qwen3:8b", "cuda", False),
    ("vulkan", 8, "qwen3:8b", "cpu", False),
    ("vulkan", 4, "qwen3:4b-instruct", "cpu", False),
    ("cpu", 0, "qwen3:4b-instruct", "cpu", True),
])
def test_faixas(backend, vram, llm, stt, swap):
    r = recommend_models(_profile(backend, vram))
    assert (r.llm, r.stt_device, r.vision_swap, r.vision) == (llm, stt, swap, "qwen3-vl:2b")
    assert r.reason


def test_escolha_do_usuario_vence_so_no_modelo_de_conversa():
    r = recommend_models(_profile("cpu", 0), chosen_llm="qwen2.5:14b")
    assert r.llm == "qwen2.5:14b" and r.vision_swap is True


@pytest.mark.parametrize("backend, vram, research", [
    ("vulkan", 12, "qwen2.5:14b"), ("nvidia", 8, "qwen2.5:14b"), ("vulkan", 16, "qwen2.5:14b"),
    ("vulkan", 4, "qwen3:8b"), ("cpu", 0, "qwen3:8b"),
])
def test_pesquisa_usa_modelo_mais_forte(backend, vram, research):
    assert recommend_models(_profile(backend, vram)).research_llm == research


def test_pesquisa_sem_o_modelo_instalado_usa_o_de_conversa(monkeypatch):
    from pidreams.core.config import CONFIG
    from pidreams.hardware import models
    from pidreams.research import agent

    monkeypatch.setattr(type(CONFIG), "ollama_model", property(lambda self: "qwen3:8b"))
    monkeypatch.setattr(type(CONFIG), "research_model", property(lambda self: "qwen2.5:14b"))
    monkeypatch.setattr(models, "ollama_model_present", lambda name: False)
    assert agent.research_model(strong=True) == ("qwen3:8b", CONFIG.ollama_keep_alive)
    monkeypatch.setattr(models, "ollama_model_present", lambda name: True)
    assert agent.research_model(strong=True) == ("qwen2.5:14b", CONFIG.research_keep_alive)
    assert agent.research_model(strong=False) == ("qwen3:8b", CONFIG.ollama_keep_alive)   # the short steps
