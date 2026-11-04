"""A janela principal monta inteira sem disparar agente, memória ou rede."""

import time

from tests.smoke.conftest import create_window


def test_janela_principal_monta(monkeypatch):
    from pidreams.ui import main_window, widgets

    from pidreams.core.settings import SETTINGS

    # Clima busca na internet numa thread: fora do teste.
    monkeypatch.setattr(widgets.WeatherFetcher, "_run", lambda self: None)
    # A aparência padrão, não a que a pessoa escolheu no PC onde o teste roda (só em memória).
    monkeypatch.setitem(SETTINGS.data, "appearance", "rosto")

    app = create_window(main_window.AgentApp)
    try:
        end = time.time() + 3
        while time.time() < end:
            app.root.update()
            time.sleep(0.03)

        from pidreams.ui.appearances.face import FaceCanvas

        assert isinstance(app._sphere, FaceCanvas)
        # Fazem parte do layout (não depende de a tela estar ligada ou desbloqueada).
        assert app._btn_mute.winfo_manager()
        assert app._btn_camera.winfo_manager()
        assert app._btn_camera.cget("text").endswith("Câmera")      # começa desligada
        assert app._chat is not None
    finally:
        app._sphere.stop()
        app.root.destroy()


def test_aparencia_troca_ao_vivo_sem_vazar_memoria(monkeypatch):
    """Troca de aparência ao vivo (10 trocas, mantendo o estado) e 100 trocas sem vazar memória."""
    import gc

    import psutil

    from pidreams.core.settings import SETTINGS
    from pidreams.ui import appearances, main_window, widgets

    monkeypatch.setattr(widgets.WeatherFetcher, "_run", lambda self: None)
    app = create_window(main_window.AgentApp)
    ids = list(appearances.CATALOG)

    def swap_val(id_):
        monkeypatch.setitem(SETTINGS.data, "appearance", id_)   # só em memória
        app._apply_settings(SETTINGS)                    # o que o salvar dispara
        app.root.update()

    try:
        app._sphere_state("speaking")
        for k in range(10):
            swap_val(ids[k % len(ids)])
            assert app._sphere.id == ids[k % len(ids)]
            assert app._sphere.state == "speaking"
            assert len(app._appearance_frame.winfo_children()) == 1

        process = psutil.Process()
        for k in range(20):                                      # aquece caches do Tk
            swap_val(ids[k % len(ids)])
        gc.collect()
        before = process.memory_info().rss
        for k in range(100):
            swap_val(ids[k % len(ids)])
        gc.collect()
        app.root.update()
        assert process.memory_info().rss - before < 10 * 1024 * 1024
    finally:
        app._sphere.stop()
        app.root.destroy()
