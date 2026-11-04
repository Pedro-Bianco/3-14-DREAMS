"""Ações no PC com a camada do Windows falsa: valores, respostas, alvo e confirmação."""

import pytest

from pidreams import pc
from pidreams.pc import audio, system, windows
from pidreams.pc.windows import Window


@pytest.fixture
def som(monkeypatch):
    estado = {"volume": 50, "mudo": False, "teclas": []}
    monkeypatch.setattr(audio, "get_volume", lambda: estado["volume"])
    monkeypatch.setattr(audio, "set_volume", lambda v: estado.update(volume=v))
    monkeypatch.setattr(audio, "get_mute", lambda: estado["mudo"])
    monkeypatch.setattr(audio, "set_mute", lambda m: estado.update(mudo=m))
    monkeypatch.setattr(audio, "media_key", lambda k: estado["teclas"].append(k))
    return estado


@pytest.fixture
def janelas(monkeypatch):
    abertas = [Window(1, "Documento A - Bloco de Notas", "notepad"), Window(2, "Notícias - Google Chrome", "chrome"),
               Window(3, "Planilha - Google Chrome", "chrome"), Window(4, "projeto - Visual Studio Code", "code")]
    feitas = []
    monkeypatch.setattr(windows, "list_windows", lambda: abertas)
    for nome in ("bring_to_front", "minimize", "maximize", "close"):
        monkeypatch.setattr(windows, nome, lambda w, n=nome: feitas.append((n, w.hwnd)))
    monkeypatch.setattr(windows, "minimize_all", lambda: feitas.append(("minimize_all", 0)))
    return feitas


def _responde(monkeypatch, sim: bool):
    perguntas = []
    monkeypatch.setattr(pc, "_CONFIRM", [lambda acao: perguntas.append(acao) or sim])
    return perguntas


# ── volume e mídia ──

def test_volume_por_valor_direcao_e_limite(som):
    assert pc.mudar_volume(valor=30) == "Volume em 30%." and som["volume"] == 30
    assert pc.mudar_volume(direcao="mais") == "Volume em 40%."
    assert pc.mudar_volume(direcao="menos") == "Volume em 30%."
    assert pc.mudar_volume(valor=150) == "Volume em 100% (é o máximo)."
    assert pc.mudar_volume().startswith("[Erro]")


def test_aumentar_com_som_mudo_tira_do_mudo(som):
    som["mudo"] = True
    pc.mudar_volume(direcao="mais")
    assert som["mudo"] is False


def test_silenciar_aceita_texto_do_modelo(som):
    assert pc.silenciar(mudo="true") == "Som mudo." and som["mudo"]
    assert pc.silenciar(mudo=False) == "Som de volta, em 50%."


def test_musica_diz_o_que_mandou_sem_afirmar_o_efeito(som):
    assert pc.controlar_musica("pausar") == "Mandei pausar o que está tocando."
    assert pc.controlar_musica("próxima") == "Mandei passar para a próxima o que está tocando."
    assert som["teclas"] == ["play_pause", "next"]
    assert pc.controlar_musica("aumentar").startswith("[Erro]")


# ── janelas ──

def test_alvo_sem_acento_e_caixa_e_nome_antes_do_titulo():
    abertas = [Window(1, "Dicas de Chrome - Bloco de Notas", "notepad"), Window(2, "Início", "chrome")]
    assert [w.hwnd for w in windows.match(abertas, "CHROME")] == [2]
    assert [w.hwnd for w in windows.match(abertas, "bloco de notas")] == [1]
    assert [w.hwnd for w in windows.match(abertas, "inicio")] == [2]
    assert windows.match(abertas, "excel") == [] and windows.match(abertas, "  ") == []


def test_lista_agrupa_por_programa(janelas):
    assert pc.ver_janelas() == "Abertos: Bloco de Notas, Chrome (2 janelas), VS Code."


def test_frente_usa_a_mais_recente_e_avisa_quando_ha_varias(janelas):
    assert pc.mexer_janela("chrome", "frente") == "Chrome em primeiro plano (há 2 janelas; trouxe a usada por último)."
    assert janelas == [("bring_to_front", 2)]


def test_app_fechado_oferece_abrir_e_a_propria_janela_e_recusada(janelas):
    assert pc.mexer_janela("Excel", "frente") == "Não achei 'Excel' aberto. Quer que eu abra?"
    assert "Encerrar" in pc.fechar_app("PI dreams") and "própria janela" in pc.mexer_janela("P-Dreams", "maximizar")
    assert janelas == []


def test_fechar_sem_sim_nao_fecha_nada(monkeypatch, janelas):
    perguntas = _responde(monkeypatch, False)
    assert pc.fechar_app("bloco de notas") == pc._CANCELLED
    assert perguntas == ["fechar o Bloco de Notas"] and janelas == []


def test_fechar_com_sim_fecha_todas_as_janelas_do_app(monkeypatch, janelas):
    perguntas = _responde(monkeypatch, True)
    assert pc.fechar_app("chrome").startswith("Pedi para fechar as 2 janelas do Chrome")
    assert perguntas == ["fechar as 2 janelas do Chrome"] and janelas == [("close", 2), ("close", 3)]


# ── sistema ──

def test_brilho_sem_tela_compativel(monkeypatch):
    monkeypatch.setattr(system, "get_brightness", lambda: None)
    assert pc.mudar_brilho(valor=40) == "Esta tela não aceita ajuste de brilho pelo PC."


def test_brilho_em_varias_telas(monkeypatch):
    monkeypatch.setattr(system, "get_brightness", lambda: 50)
    monkeypatch.setattr(system, "set_brightness", lambda v: 2)
    assert pc.mudar_brilho(direcao="menos") == "Brilho em 40% nas 2 telas."


def test_comando_de_desligar():
    assert system.shutdown_command("desligar", 300)[:4] == ["shutdown", "/s", "/t", "300"]
    assert system.shutdown_command("reiniciar", 60)[1] == "/r"


@pytest.mark.parametrize("acao,pergunta", [(lambda: pc.desligar_pc(), "desligar o PC em 1 minuto"),
                                           (lambda: pc.reiniciar_pc(5), "reiniciar o PC em 5 minutos"),
                                           (lambda: pc.bloquear_pc(), "bloquear o PC")])
def test_acoes_de_energia_sem_sim_nao_acontecem(monkeypatch, acao, pergunta):
    feitas = []
    monkeypatch.setattr(system, "schedule", lambda *a: feitas.append(a))
    monkeypatch.setattr(system, "lock", lambda: feitas.append("lock"))
    perguntas = _responde(monkeypatch, False)
    assert acao() == pc._CANCELLED
    assert perguntas == [pergunta] and feitas == []


def test_desligar_com_sim_agenda_e_cancelar_nao_pergunta(monkeypatch):
    feitas = []
    monkeypatch.setattr(system, "schedule", lambda modo, s: feitas.append((modo, s)))
    monkeypatch.setattr(system, "cancel_shutdown", lambda: True)
    perguntas = _responde(monkeypatch, True)
    assert pc.desligar_pc(5).startswith("O PC desliga às ")
    assert feitas == [("desligar", 300)]
    perguntas.clear()
    assert pc.cancelar_desligamento() == "Desligamento cancelado." and perguntas == []


def test_prazo_fora_da_faixa(monkeypatch):
    _responde(monkeypatch, True)
    assert pc.desligar_pc(60 * 25).startswith("[Erro]")
    assert pc.reiniciar_pc("logo").startswith("[Erro]")


# ── cancelar desligamento por código (o modelo falhou no teste real de 2026-11-01) ──

@pytest.mark.parametrize("frase", ["Cancela o desligamento! Cancela!", "cancele", "não desliga não",
                                   "para o desligamento", "para de desligar", "pare!", "aborta", "desisti"])
def test_frases_de_cancelar(frase):
    assert pc.is_cancel_request(frase)


@pytest.mark.parametrize("frase", ["volume para 30", "abre o bloco de notas", "obrigado", "pausa a música"])
def test_frases_que_nao_cancelam(frase):
    assert not pc.is_cancel_request(frase)


def test_desligamento_fica_pendente_ate_cancelar_ou_passar_a_hora(monkeypatch):
    import datetime as dt

    monkeypatch.setattr(system, "schedule", lambda *a: None)
    monkeypatch.setattr(system, "cancel_shutdown", lambda: True)
    monkeypatch.setattr(pc, "_PENDING", [None])
    _responde(monkeypatch, True)
    pc.reiniciar_pc(5)
    modo, prazo = pc.pending_shutdown()
    assert modo == "reiniciar" and prazo > dt.datetime.now()
    assert pc.cancelar_desligamento() == "Desligamento cancelado." and pc.pending_shutdown() is None
    pc._PENDING[0] = ("desligar", dt.datetime.now() - dt.timedelta(seconds=1))
    assert pc.pending_shutdown() is None
