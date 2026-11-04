"""Configurações salvas valem sem reiniciar: prompt, voz, dispositivos."""

import pytest

from pidreams.core.settings import Settings
from tests.smoke.conftest import create_window


@pytest.fixture
def st(tmp_path, monkeypatch):
    """Settings isolado, colocado no lugar do global em todos os módulos que o usam."""
    s = Settings(tmp_path / "settings.json")
    for module in ("pidreams.core.settings", "pidreams.agent.llm", "pidreams.audio.tts",
                   "pidreams.ui.main_window", "pidreams.core.config", "pidreams.ui.panels.audio",
                   "pidreams.ui.panels.apps", "pidreams.ui.first_run"):
        monkeypatch.setattr(f"{module}.SETTINGS", s, raising=False)
    return s


def test_tratamento_e_persona_valem_na_proxima_mensagem(st):
    from pidreams.agent.llm import LLMAgent

    agent = LLMAgent()
    st.set("treatment", "Ana"); st.set("persona_id", "formal"); st.save()
    prompt = agent.history[0]["content"]
    assert 'Chame o usuário de "Ana"' in prompt and "linguagem formal" in prompt


def test_trocar_voz_recarrega_o_tts(st, fake_sound, monkeypatch):
    from pidreams.audio import tts as tts_mod
    from pidreams.audio import voices

    engine = tts_mod.TTSEngine()
    engine.start()
    other = next(v for v in voices.choices() if v != voices.resolve(st.get("voice.model")))
    swaps = []
    monkeypatch.setattr(engine, "_load_voice", swaps.append)
    st.set("voice.model", other); st.save()
    import time
    for _ in range(50):
        if swaps:
            break
        time.sleep(0.05)
    assert swaps == [other]


def test_trocar_microfone_atualiza_a_janela(st, fake_sound, monkeypatch):
    from pidreams.audio import devices
    from pidreams.ui import main_window, widgets

    monkeypatch.setattr(widgets.WeatherFetcher, "_run", lambda self: None)
    monkeypatch.setattr(devices, "index", lambda name, kind: 7 if name == "Microfone USB" else None)
    app = create_window(main_window.AgentApp)
    try:
        st.set("audio.input_device", "Microfone USB"); st.save()
        app.root.update()
        assert app._mic_device_ref[0] == 7
    finally:
        app._sphere.stop()
        app.root.destroy()


def test_microfone_desplugado_avisa_e_some_ao_voltar(st, fake_sound, monkeypatch):
    from pidreams.audio import devices
    from pidreams.ui import main_window, widgets

    monkeypatch.setattr(widgets.WeatherFetcher, "_run", lambda self: None)
    connected = {"Microfone USB": 7}
    monkeypatch.setattr(devices, "index", lambda name, kind: connected.get(name))
    st.set("audio.input_device", "Microfone USB"); st.save()
    connected.clear()                                 # desplugado entre sessões
    app = create_window(main_window.AgentApp)
    try:
        notice = app._notices.current()
        assert notice["code"] == "device_input" and "padrão do Windows" in notice["msg"]
        connected["Microfone USB"] = 7                # plugou de novo e salvou
        st.save(); app.root.update()
        assert app._notices.current() is None
    finally:
        app._sphere.stop()
        app.root.destroy()


def test_valor_invalido_e_recusado_sem_salvar(st):
    with pytest.raises(ValueError):
        st.set("ollama.timeout_s", 5)
    assert st.get("ollama.timeout_s") == 600.0


def test_tela_salva_e_recusa_invalido_sem_gravar_pela_metade(st, fake_sound, monkeypatch):
    import tkinter as tk

    from pidreams.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr("pidreams.ui.settings_dialog._installed_models", lambda: ["qwen2.5:7b"])
    monkeypatch.setattr("pidreams.hardware.models.kokoro_present", lambda: True)   # no voice download first
    monkeypatch.setattr("pidreams.hardware.models.pocket_present", lambda: True)
    root_dir = create_window(tk.Tk)
    try:
        screen = SettingsDialog(root_dir, st)
        screen.v["treatment"].set("Bia")
        screen.v["ollama.timeout_s"].set(5)            # fora da faixa
        screen.save()
        assert "corrija" in screen._status.cget("text")
        assert st.get("treatment") == ""             # nada salvo pela metade
        screen.v["ollama.timeout_s"].set(120)
        screen.save()
        assert st.get("treatment") == "Bia" and st.get("ollama.timeout_s") == 120
    finally:
        root_dir.destroy()
