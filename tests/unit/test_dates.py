"""Datas faladas viram datas de verdade. Referência fixa: sexta, 30/10/2026, 10:00."""

import datetime as dt

import pytest

from pidreams.core.dates import InvalidDate, resolve_when

NOW = dt.datetime(2026, 10, 30, 10, 0)          # uma sexta-feira


def _r(text, **kw):
    return resolve_when(text, NOW, **kw)


@pytest.mark.parametrize("text, data, hour", [
    ("amanhã", dt.date(2026, 10, 31), None),
    ("depois de amanhã", dt.date(2026, 11, 1), None),
    ("hoje às 15h", dt.date(2026, 10, 30), dt.time(15)),
    ("sexta", dt.date(2026, 11, 6), None),                         # numa sexta: a próxima
    ("na segunda-feira", dt.date(2026, 11, 2), None),
    ("sábado de manhã", dt.date(2026, 10, 31), dt.time(9)),
    ("terça à noite", dt.date(2026, 11, 3), dt.time(20)),
    ("dia 12", dt.date(2026, 11, 12), None),                       # o próximo dia 12
    ("dia 30 às 18:30", dt.date(2026, 10, 30), dt.time(18, 30)),
    ("12/11", dt.date(2026, 11, 12), None),
    ("5/1", dt.date(2027, 1, 5), None),                            # já passou neste ano
    ("25 de dezembro", dt.date(2026, 12, 25), None),
    ("2026-12-25", dt.date(2026, 12, 25), None),
    ("daqui a 3 dias", dt.date(2026, 11, 2), None),
    ("daqui a duas semanas", dt.date(2026, 11, 13), None),
    ("semana que vem", dt.date(2026, 11, 2), None),
    ("amanhã às 3 da tarde", dt.date(2026, 10, 31), dt.time(15)),
    ("às 15h", dt.date(2026, 10, 30), dt.time(15)),                # só a hora: hoje, se não passou
    ("às 9h", dt.date(2026, 10, 31), dt.time(9)),                  # já passou: amanhã
    # Vistos no app em 2026-11-09: o modelo passa as palavras como foram ditas.
    ("dois minutos", dt.date(2026, 10, 30), dt.time(10, 2)),
    ("daqui a 2 minutos", dt.date(2026, 10, 30), dt.time(10, 2)),
    ("em meia hora", dt.date(2026, 10, 30), dt.time(10, 30)),
    ("daqui a uma hora", dt.date(2026, 10, 30), dt.time(11)),
    ("11 e 21", dt.date(2026, 10, 30), dt.time(11, 21)),
    ("às 15 e 45", dt.date(2026, 10, 30), dt.time(15, 45)),
    ("às 3 horas da tarde", dt.date(2026, 10, 30), dt.time(15)),   # hora do relógio, não "daqui a 3 h"
])
def test_formatos_falados(text, data, hour):
    assert _r(text) == (data, hour)


def test_daqui_a_minutos_nunca_dispara_antes():
    with_seconds = dt.datetime(2026, 10, 30, 10, 0, 40)
    assert resolve_when("daqui a 2 minutos", with_seconds) == (dt.date(2026, 10, 30), dt.time(10, 3))


def test_agenda_conta_hoje_e_aceita_passado():
    assert _r("sexta", include_today=True)[0] == dt.date(2026, 10, 30)
    assert _r("ontem", allow_past=True)[0] == dt.date(2026, 10, 29)


@pytest.mark.parametrize("text, error", [
    ("ontem", "já passou"), ("hoje às 8h", "já passou"),
    ("quando der", "Não entendi"), ("", "Não entendi"), ("dia 31 de fevereiro", "Não entendi"),
])
def test_passado_e_incompreensivel(text, error):
    with pytest.raises(InvalidDate, match=error):
        _r(text)
