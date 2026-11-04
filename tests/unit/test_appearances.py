"""Aparências do painel central: catálogo, reserva, pausa, estados e volume."""

import random
import tkinter as tk
from types import SimpleNamespace

import pytest

from pidreams.ui import appearances
from pidreams.ui.appearances import base, holo


@pytest.fixture(scope="module")
def root_dir():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("sem tela para o Tk")
    r.withdraw()
    yield r
    r.destroy()


def test_catalogo_tem_as_quatro_com_nome():
    assert list(appearances.CATALOG) == ["rosto", "nucleo", "cerebro", "orbe"]
    assert all(appearances.names().values())
    assert all(appearances.fallback(i) in appearances.CATALOG for i in appearances.CATALOG)


def test_id_desconhecido_cria_o_rosto(root_dir):
    a = appearances.create("nao-existe", root_dir, size=200, bg="#010a14")
    assert a.id == "rosto"
    a.stop()


def test_criacao_que_falha_cai_na_reserva(root_dir, monkeypatch):
    def break_at(*_a, **_k):
        raise OSError("imagem do rosto ausente")
    name, _, res = appearances.CATALOG["rosto"]
    monkeypatch.setitem(appearances.CATALOG, "rosto", (name, break_at, res))
    a = appearances.create("rosto", root_dir, size=200, bg="#010a14")
    assert a.id == "orbe"
    a.stop()


class _Broken(base.Appearance):
    def __init__(self, parent, on_fail):
        super().__init__(parent, 50, 50, "#000000", on_fail)
        self.frames = 0

    def _frame_holder(self):
        self.frames += 1
        raise ValueError("desenho quebrado")


def test_tres_quadros_com_erro_chamam_a_reserva_uma_vez(root_dir):
    calls = []
    a = _Broken(root_dir, on_fail=lambda: calls.append(1))
    for _ in range(5):
        a._loop()
    assert calls == [1]
    a.stop()


def test_minimizada_nao_desenha(root_dir):
    a = _Broken(root_dir, on_fail=None)
    a.winfo_toplevel = lambda: SimpleNamespace(state=lambda: "iconic")
    a._loop()
    assert a.frames == 0
    a.stop()


def test_estado_desconhecido_vira_ocioso(root_dir):
    a = _Broken(root_dir, on_fail=None)
    a.set_state("dançando")
    assert a.state == "idle"
    a.set_state("speaking")
    assert a.state == "speaking"
    a.stop()


def _drawing(a, images):
    if isinstance(a, holo.HoloAppearance):
        return images[-1]
    return tuple((tuple(a.coords(i)), a.itemcget(i, "fill") if a.type(i) != "line" else "")
                 for i in a.find_all())


@pytest.mark.parametrize("id_", ["rosto", "nucleo", "cerebro", "orbe"])
def test_falando_segue_o_volume_da_voz(root_dir, monkeypatch, id_):
    images = []
    paste = holo.ImageTk.PhotoImage.paste
    monkeypatch.setattr(holo.ImageTk.PhotoImage, "paste",
                        lambda self, img, *a: images.append(img.tobytes()) or paste(self, img, *a))
    monkeypatch.setattr(holo.HoloAppearance, "winfo_pointerxy", lambda self: (0, 0))   # mouse parado

    def draws(volume):
        monkeypatch.setattr(base, "_voice_level", lambda: volume)
        random.seed(7)                     # mesmas partículas nas duas cópias
        a = appearances.create(id_, root_dir, size=200, bg="#010a14")
        a.stop()                           # quadros só pelas chamadas abaixo
        a.set_state("speaking")
        for _ in range(12):
            a._running = True
            a._loop()
            a._running = False
        result = _drawing(a, images)
        a.destroy()
        return result

    assert draws(0.20) == draws(0.20)  # controle: o desenho é reproduzível
    assert draws(0.02) != draws(0.20)  # e muda com o volume
