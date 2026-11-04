"""Downloads de modelos: disco, modelo já presente, progresso e falhas legíveis."""

import threading
from types import SimpleNamespace

import pytest

from pidreams.hardware import models


def test_falta_de_espaco_vira_mensagem_legivel(tmp_path, monkeypatch):
    monkeypatch.setattr(models.shutil, "disk_usage", lambda _p: SimpleNamespace(free=1 * 1024**3))
    with pytest.raises(models.DownloadFailed, match=r"Faltam .* GB"):
        models.check_space(tmp_path, 5 * 1024**3)


def _client_of(present_items, eventos):
    return SimpleNamespace(
        list=lambda: SimpleNamespace(models=[SimpleNamespace(model=m) for m in present_items]),
        pull=lambda name, stream: iter(eventos),
    )


def test_modelo_presente_nao_baixa(monkeypatch):
    monkeypatch.setattr(models, "_client_of", lambda: _client_of(["qwen2.5:7b"], []))
    seen = []
    models.download_ollama("qwen2.5:7b", lambda p, t: seen.append(p), threading.Event())
    assert seen == [100]


def test_download_reporta_progresso_e_respeita_cancelar(monkeypatch, tmp_path):
    ev = [SimpleNamespace(status="baixando", completed=c, total=100) for c in (10, 50, 100)]
    monkeypatch.setattr(models, "_client_of", lambda: _client_of([], ev))
    monkeypatch.setattr(models, "check_space", lambda *_a: None)
    seen = []
    models.download_ollama("qwen2.5:3b", lambda p, t: seen.append(round(p)), threading.Event())
    assert seen[:3] == [10, 50, 100]

    cancel = threading.Event(); cancel.set()
    monkeypatch.setattr(models, "_client_of", lambda: _client_of([], ev))
    with pytest.raises(models.Cancelled):
        models.download_ollama("qwen2.5:3b", lambda *_: None, cancel)


def test_erro_de_rede_vira_falha_legivel(monkeypatch):
    def pull(*_a, **_kw):
        raise ConnectionError("sem rede")
    monkeypatch.setattr(models, "_client_of", lambda: SimpleNamespace(
        list=lambda: SimpleNamespace(models=[]), pull=pull))
    with pytest.raises(models.DownloadFailed, match="Não foi possível baixar qwen2.5:3b"):
        models.download_ollama("qwen2.5:3b", lambda *_: None, threading.Event())
