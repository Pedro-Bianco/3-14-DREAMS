"""Cada falha conhecida vira aviso acionável em até 15 s, nunca espera infinita."""

import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest

from pidreams.agent import problems
from pidreams.core.settings import SETTINGS
from pidreams.hardware import models, ollama_supervisor as sup


def _collect(coroutine_factory, until_code, limit_s=15):
    """Roda a espera do agente até aparecer o aviso pedido; devolve (aviso, segundos)."""
    eventos, stop = [], asyncio.Event()

    def emit(kind, data=None):
        eventos.append((kind, data))
        if kind == "problem" and data["code"] == until_code:
            stop.set()

    async def run():
        start_at = time.time()
        result = await asyncio.wait_for(coroutine_factory(emit, stop), timeout=limit_s + 5)
        return result, time.time() - start_at

    result, seconds = asyncio.run(run())
    notices = [d for t, d in eventos if t == "problem"]
    return result, notices, seconds


@pytest.fixture
def server_stuck(monkeypatch):
    """Aceita a conexão e nunca responde — o defeito de 2026-10-16."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen()
    port = s.getsockname()[1]
    def accept_fn():
        try:
            while True:
                s.accept()
        except OSError:
            pass                      # socket fechado no fim do teste
    threading.Thread(target=accept_fn, daemon=True).start()
    monkeypatch.setitem(SETTINGS.data["ollama"], "host", f"http://127.0.0.1:{port}")
    yield
    s.close()


def test_ollama_travado_vira_aviso_com_reiniciar(server_stuck, monkeypatch, tmp_path):
    exe = tmp_path / "ollama.exe"; exe.write_text("")
    monkeypatch.setattr(sup, "install_folder", lambda: tmp_path)
    monkeypatch.setattr(sup, "port_owner", lambda: (1, str(exe)))
    result, notices, seconds = _collect(problems.wait_for_ollama, "ollama")
    assert result is False                          # parou porque pedimos, não travou
    assert seconds <= 15
    assert notices[0]["actions"][0][1] == "ollama_restart"


def test_outro_programa_na_porta_mostra_o_caminho(monkeypatch):
    monkeypatch.setattr(sup, "port_owner", lambda: (1, r"C:\outro\servidor.exe"))
    monkeypatch.setattr(sup, "install_folder", lambda: Path(r"C:\Programas\Ollama"))
    _, notices, seconds = _collect(problems.wait_for_ollama, "ollama")
    assert seconds <= 15 and r"C:\outro\servidor.exe" in notices[0]["msg"]


def test_modelo_ausente_avisa_e_resolve_sozinho(monkeypatch):
    present = {"valor": False}
    monkeypatch.setattr(models, "ollama_model_present", lambda _n: present["valor"])
    monkeypatch.setattr(problems, "INTERVAL_S", 0.5)
    eventos = []

    async def run():
        task = asyncio.create_task(problems.wait_for_model(lambda t, d=None: eventos.append((t, d))))
        await asyncio.sleep(0.3)
        present["valor"] = True                       # o usuário clicou em BAIXAR
        return await asyncio.wait_for(task, timeout=10)

    assert asyncio.run(run()) is True
    assert [t for t, _ in eventos] == ["problem", "resolved"]
    assert eventos[0][1]["actions"][0][1] == "download_model"


def test_camera_bloqueada_pela_privacidade(monkeypatch):
    monkeypatch.setattr(problems, "_denied", lambda resource: resource == "webcam")
    notice = problems.from_camera(RuntimeError("não abriu"))
    assert notice["actions"][0][1] == "camera_privacy"
    monkeypatch.setattr(problems, "_denied", lambda resource: False)
    assert problems.from_camera(RuntimeError("sem câmera"))["level"] == "warning"


def test_falha_na_resposta_oferece_tentar_de_novo():
    notice = problems.from_chat(ConnectionError("Failed to connect"))
    assert [a for _, a in notice["actions"]] == ["ollama_restart", "retry"]


def test_faixa_de_avisos_mostra_e_some(fake_sound):
    import tkinter as tk

    from pidreams.ui.notice_bar import NoticeBar
    from tests.smoke.conftest import create_window

    root_dir = create_window(tk.Tk)
    try:
        actions = []
        bar = NoticeBar(root_dir, lambda a, av: actions.append(a))
        bar.grid(row=0, column=0)
        bar.show(problems.problem("ollama", "O Ollama está fechado.", [("INICIAR", "ollama_start")]))
        root_dir.update()
        assert bar.winfo_ismapped()
        button = bar._buttons.winfo_children()[0]
        button.invoke()
        assert actions == ["ollama_start"]
        bar.resolve("ollama"); root_dir.update()
        assert not bar.winfo_ismapped()
    finally:
        root_dir.destroy()
