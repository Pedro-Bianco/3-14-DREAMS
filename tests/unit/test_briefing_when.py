"""Resumo ao abrir: uma vez por dia, toda vez que abrir ou desligado. A tela grava as duas chaves
(ligado, toda_vez) num arquivo de configurações temporário — nunca no settings.json real."""

import tkinter as tk

import pytest

from pidreams.core.settings import Settings


@pytest.fixture(scope="module")
def tk_root():
    from pidreams.ui import theme
    root = tk.Tk()
    root.withdraw()
    theme.init(root)
    yield root
    root.destroy()


@pytest.fixture(autouse=True)
def _voices_present(monkeypatch):
    """Without the voice files, saving downloads them first (a fresh machine, as in CI)."""
    from pidreams.hardware import models
    monkeypatch.setattr(models, "kokoro_present", lambda: True)
    monkeypatch.setattr(models, "pocket_present", lambda: True)


def _dialog(tk_root, tmp_path, **values):
    from pidreams.ui.settings_dialog import SettingsDialog
    st = Settings(tmp_path / "settings.json")
    for key, value in values.items():
        st.set(key, value)
    return SettingsDialog(tk_root, st), st


@pytest.mark.parametrize("label,ligado,toda_vez", [
    ("Uma vez por dia", True, False),
    ("Toda vez que abrir", True, True),
    ("Desligado", False, False),
])
def test_escolha_grava_as_duas_chaves(tk_root, tmp_path, label, ligado, toda_vez):
    dialog, st = _dialog(tk_root, tmp_path)
    dialog._briefing_when.set(label)
    dialog.save()
    assert (st.get("resumo.ligado"), st.get("resumo.toda_vez")) == (ligado, toda_vez)
    dialog.window.destroy()


def test_resumo_desligado_antes_continua_desligado(tk_root, tmp_path):
    dialog, _st = _dialog(tk_root, tmp_path, **{"resumo.ligado": False})
    assert dialog._briefing_when.get() == "Desligado"
    dialog.window.destroy()
