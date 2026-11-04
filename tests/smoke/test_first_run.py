"""Assistente de primeiro uso: percorre as 5 etapas e grava as escolhas."""

import sounddevice as sd

from pidreams.core.settings import Settings
from tests.smoke.conftest import create_window


def test_assistente_grava_as_escolhas(tmp_path, fake_sound, monkeypatch):
    monkeypatch.setattr(sd, "play", lambda *a, **kw: None)
    from pidreams.ui.first_run import FirstRunWizard

    st = Settings(tmp_path / "settings.json")
    w = create_window(lambda: FirstRunWizard(st))
    try:
        w._name.set("Sexta-feira")
        w._treatment.set("Ana")
        for step in range(5):
            w.root.update()
            assert w._title.cget("text")
            if step == 1:
                w._persona.set("formal")
            if step == 2:
                w._test_sound()
            if step == 3:
                w._city.set("Curitiba")
            w.advance()
    finally:
        if not w.finished:            # concluir já destrói a janela
            w.root.destroy()

    assert w.finished
    saved = Settings(tmp_path / "settings.json")
    assert saved.get("first_run_done") is True
    assert saved.get("assistant_name") == "Sexta-feira"
    assert saved.get("treatment") == "Ana"
    assert saved.get("persona_id") == "formal"
    assert saved.get("weather.city") == "Curitiba"


def test_fechar_o_assistente_nao_marca_como_concluido(tmp_path, fake_sound):
    from pidreams.ui.first_run import FirstRunWizard

    st = Settings(tmp_path / "settings.json")
    w = create_window(lambda: FirstRunWizard(st))
    w._cancel()
    assert not w.finished
    assert Settings(tmp_path / "settings.json").get("first_run_done") is False
