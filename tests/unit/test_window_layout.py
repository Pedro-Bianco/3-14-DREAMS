"""Layout responsivo da janela principal: colunas, tamanho da aparência e posição lembrada."""

import pytest

from pidreams.ui import appearances, theme


@pytest.fixture(autouse=True)
def _escala_100(monkeypatch):
    monkeypatch.setattr(theme, "_scale", [1.0])


@pytest.mark.parametrize("width", [1024, 1150, 1366, 1920, 3440])
def test_colunas_respeitam_minimos_e_o_chat_nao_passa_de_720(width):
    left, center, chat = theme.columns(width)
    assert 280 <= left <= 340
    assert 360 <= chat <= 720
    assert center > 0
    assert left + center + chat <= width


def test_espaco_extra_das_telas_largas_vai_para_o_centro():
    _, centro_1920, chat_1920 = theme.columns(1920)
    _, centro_3440, chat_3440 = theme.columns(3440)
    assert chat_3440 == 720 and centro_3440 - centro_1920 > 1400


@pytest.mark.parametrize("id_", ["nucleo", "cerebro", "orbe"])
@pytest.mark.parametrize("screen", [(1920, 1080), (3440, 1440)])
def test_aparencia_ocupa_metade_da_altura_util_maximizada(id_, screen):
    width, height = screen
    _, center, _ = theme.columns(width)
    area_h = height - 420                 # cabeçalho, aviso, controles e rodapé (medido na captura)
    size, _ = theme.appearance_fit(center, area_h, appearances.max_size(id_))
    assert size >= 0.5 * area_h


def test_rosto_cresce_ao_menos_1_6_vez_no_ultrawide():
    _, center, _ = theme.columns(3440)
    size, _ = theme.appearance_fit(center, 1020, appearances.max_size("rosto"))
    assert size >= 1.6 * 300


def test_cartoes_hoje_so_com_sobra_de_largura():
    _, center_max, _ = theme.columns(3440)
    _, center_note, _ = theme.columns(1366)
    assert theme.appearance_fit(center_max, 1000, 800)[1] is True
    assert theme.appearance_fit(center_note, 500, 800)[1] is False


def test_primeira_abertura_centraliza_a_80_por_cento():
    assert theme.initial_geometry("", 1920, 1080, lambda x, y: True) == "1440x864+240+108"


def test_posicao_salva_visivel_e_restaurada():
    assert theme.initial_geometry("1200x700+100+50", 1920, 1080, lambda x, y: True) == "1200x700+100+50"


def test_posicao_fora_da_tela_volta_ao_centro():
    geo = theme.initial_geometry("1200x700+-2500+50", 1920, 1080, lambda x, y: x >= 0)
    assert geo == "1440x864+240+108"


def test_tamanho_salvo_abaixo_do_minimo_e_ignorado():
    assert theme.initial_geometry("500x300+10+10", 1920, 1080, lambda x, y: True) == "1440x864+240+108"


def test_tela_pequena_nao_abre_maior_que_a_tela():
    w, h = map(int, theme.initial_geometry("", 1366, 768, lambda x, y: True).split("+")[0].split("x"))
    assert w <= 1366 and h <= 768
