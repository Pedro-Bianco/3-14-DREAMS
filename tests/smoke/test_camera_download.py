"""Ligar a câmera sem o modelo de visão baixa o modelo antes.

Roda dentro do mainloop do Tk, como o app: as threads de trabalho agendam a volta
para a interface com root.after, o que o Tk só aceita com o laço principal ativo.
"""

import pytest

from tests.smoke.conftest import create_window


@pytest.mark.parametrize("present", [True, False])
def test_camera_liga_com_ou_sem_download(monkeypatch, fake_camera, present):
    from pidreams.hardware import models
    from pidreams.ui import main_window, widgets

    monkeypatch.setattr(widgets.WeatherFetcher, "_run", lambda self: None)
    monkeypatch.setattr(models, "ollama_model_present", lambda _n: present)
    downloaded = []

    def download(name, progress, _cancel):
        progress(50, "baixando"); progress(100, "pronto"); downloaded.append(name)
    monkeypatch.setattr(models, "download_ollama", download)

    app = create_window(main_window.AgentApp)
    camera = app._services.get("camera")
    steps = {"ligou": False, "desligou": False}

    def wait_until(condition, after_val, limit=500):     # 20 s: folga para máquina sob carga
        if condition():
            after_val()
        elif limit:
            app.root.after(40, wait_until, condition, after_val, limit - 1)
        else:
            app.root.quit()

    def is_ready(enabled):
        # como o usuário: só clica de novo quando o botão volta a ficar habilitado
        return lambda: camera.running == enabled and str(app._btn_camera.cget("state")) == "normal"

    def stop_connection():
        steps["ligou"] = True
        app._btn_camera.invoke()
        wait_until(is_ready(False), end)

    def end():
        steps["desligou"] = True
        app.root.quit()

    app.root.after(300, lambda: (app._btn_camera.invoke(), wait_until(is_ready(True), stop_connection)))
    try:
        app.root.mainloop()
    finally:
        app._sphere.stop()
        app.root.destroy()

    assert steps == {"ligou": True, "desligou": True}
    assert len(downloaded) == (0 if present else 1)
