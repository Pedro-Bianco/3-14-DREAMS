"""Lembretes: guardar, vencer, concluir e apagar, num LOCALAPPDATA temporário."""

import datetime as dt

import pytest

from pidreams import reminders

FRIDAY = dt.datetime(2026, 10, 30, 10, 0)


@pytest.fixture(autouse=True)
def temp_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_criar_confirma_com_data_por_extenso_e_sobrevive():
    assert reminders.criar_lembrete("pagar a conta de luz", "sexta", FRIDAY) == \
        "Guardado: pagar a conta de luz — sexta, 6 de novembro."
    assert "às 15:00" in reminders.criar_lembrete("ligar para a escola", "amanhã às 15h", FRIDAY)
    assert [l["texto"] for l in reminders.pending_items()] == ["ligar para a escola", "pagar a conta de luz"]
    assert reminders.file().is_file()                      # sobrevive ao fechar o app


def test_sem_data_pede_e_passado_recusa():
    assert "pergunte ao usuário quando" in reminders.criar_lembrete("comprar pão", "", FRIDAY)
    assert "já passou" in reminders.criar_lembrete("comprar pão", "ontem", FRIDAY)
    assert reminders.pending_items() == []


def test_vencidos_e_avisados():
    reminders.criar_lembrete("consulta", "amanhã às 15h", FRIDAY)
    reminders.criar_lembrete("aniversário da Ana", "amanhã", FRIDAY)
    saturday_early = dt.datetime(2026, 10, 31, 8, 0)
    assert [l["texto"] for l in reminders.due_reminders(saturday_early)] == ["aniversário da Ana"]
    saturday_afternoon = dt.datetime(2026, 10, 31, 15, 0)
    due = reminders.due_reminders(saturday_afternoon)
    assert len(due) == 2
    reminders.mark_notified([l["id"] for l in due])
    assert reminders.due_reminders(saturday_afternoon, only_new=True) == []
    assert len(reminders.due_reminders(saturday_afternoon)) == 2           # avisado continua até concluir
    sunday = dt.datetime(2026, 11, 1, 9, 0)
    assert "(atrasado)" in reminders.describe(reminders.due_reminders(sunday)[0], sunday)


def test_concluir_apagar_e_ambiguidade():
    for text in ("pagar a conta de luz", "pagar a conta de água", "ligar para a escola"):
        reminders.criar_lembrete(text, "segunda", FRIDAY)
    assert "Achei mais de um" in reminders.tirar_lembrete("pagar a conta")
    assert reminders.tirar_lembrete("conta de luz") == "Tirado da lista: pagar a conta de luz."
    assert reminders.tirar_lembrete("escola") == "Tirado da lista: ligar para a escola."
    assert "Não achei" in reminders.tirar_lembrete("dentista")
    assert "conta de água" in reminders.ver_lembretes(FRIDAY)
    assert "luz" not in reminders.ver_lembretes(FRIDAY)


def test_ultimo_resumo():
    assert reminders.last_briefing() == ""
    reminders.record_briefing(FRIDAY.date())
    assert reminders.last_briefing() == "2026-10-30"
