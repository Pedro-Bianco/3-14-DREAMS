"""Resumo ao abrir com fontes falsas: partes, falhas, limite de tempo, só lembretes."""

import datetime as dt
import time

from pidreams import briefing

FRIDAY_9AM = dt.datetime(2026, 10, 30, 9, 0)
CALENDAR = ("sexta, 30 de outubro, 08:00–08:30: Corrida — Parque\n"
          "sexta, 30 de outubro, 10:00–11:00: Dentista Fictício — Rua Exemplo, 100\n"
          "sexta, 30 de outubro, dia todo: Aniversário da Ana")
EMAILS = ("id 7 | de: Banco Fictício <a@example.org> | assunto: Fatura | data: x | NÃO LIDO\n"
          "id 6 | de: Ana Exemplo <ana@example.com> | assunto: Oi | data: x | NÃO LIDO\n"
          "id 5 | de:  <sem@example.com> | assunto: ? | data: x | NÃO LIDO\n"
          "id 4 | de: Escola <e@example.org> | assunto: Reunião | data: x | NÃO LIDO")


def test_cumprimento_pela_hora():
    assert briefing.greeting(FRIDAY_9AM, "chefe") == "Bom dia, chefe."
    assert briefing.greeting(FRIDAY_9AM.replace(hour=14)) == "Boa tarde."
    assert briefing.greeting(FRIDAY_9AM.replace(hour=21)) == "Boa noite."


def test_resumo_completo_com_todas_as_partes():
    sources_map = {"clima": lambda: briefing.weather_phrase({"city": "Recife", "temp": "28", "desc": "Ensolarado"}),
              "agenda": lambda: briefing.calendar_phrase(CALENDAR, FRIDAY_9AM),
              "emails": lambda: briefing.emails_phrase(EMAILS),
              "lembretes": lambda: "Lembrete: pagar a conta de luz — sexta, 30 de outubro."}
    text = briefing.build(FRIDAY_9AM, sources_map, full_briefing=True, treatment="chefe")
    assert text.startswith("Bom dia, chefe. Hoje é sexta, 30 de outubro. Em Recife, 28 graus, ensolarado.")
    assert "às 10:00, Dentista Fictício" in text and "Corrida" not in text     # 8h já passou
    assert "Aniversário da Ana, o dia todo" in text
    assert "4 e-mails não lidos; os mais recentes de Banco Fictício, Ana Exemplo e remetente sem nome." in text
    assert text.endswith("Lembrete: pagar a conta de luz — sexta, 30 de outubro.")


def test_parte_que_falha_ou_demora_some_sem_segurar():
    def break_at():
        raise OSError("sem internet")

    def slow():
        time.sleep(5)
        return "nunca"

    start_at = time.time()
    text = briefing.build(FRIDAY_9AM, {"clima": break_at, "agenda": slow, "emails": lambda: "Nenhum e-mail novo."},
                          full_briefing=True, limit_s=0.5)
    assert time.time() - start_at < 2
    assert text == "Bom dia. Hoje é sexta, 30 de outubro. Nenhum e-mail novo."


def test_reaberto_no_mesmo_dia_so_lembretes():
    sources_map = {"clima": lambda: "Em Recife, 28 graus.", "lembretes": lambda: "Lembrete: consulta."}
    assert briefing.build(FRIDAY_9AM, sources_map, full_briefing=False) == "Bom dia. Lembrete: consulta."


def test_frases_de_agenda_vazia_e_muitos_lembretes():
    assert briefing.calendar_phrase("Nenhum compromisso em sexta.", FRIDAY_9AM) == "Sua agenda está livre hoje."
    assert briefing.calendar_phrase(CALENDAR.splitlines()[0], FRIDAY_9AM) == "Não tem mais nada na agenda hoje."
    items = [{"texto": f"item {i}", "data": "2026-10-30", "hora": None} for i in range(7)]
    assert briefing.reminders_phrase(items, FRIDAY_9AM).endswith("; e mais 2.")
    assert briefing.emails_phrase("Nenhum e-mail encontrado.") == "Nenhum e-mail novo."


# ── fontes do resumo, usadas também pelos cartões "Hoje" ─────────────────────

class _ConexoesFalsas:
    def __init__(self, ativas):
        self.ativas, self.chamadas = ativas, []

    def connected(self):
        return self.ativas

    def call(self, id_, tool, arguments):
        self.chamadas.append(id_)
        return "Nenhum evento." if id_ == "agenda" else "Nenhum e-mail."


def test_fontes_seguem_as_partes_ligadas_e_as_conexoes_ativas(monkeypatch):
    from pidreams.core.config import CONFIG

    monkeypatch.setattr(type(CONFIG), "weather_city", property(lambda self: "Cidade Exemplo"))
    agora = dt.datetime(2026, 10, 31, 9, 0)
    todas = briefing.sources(_ConexoesFalsas(["agenda", "gmail"]), agora, {}, [])
    assert set(todas) == {"clima", "agenda", "emails", "lembretes"}
    sem_gmail = briefing.sources(_ConexoesFalsas(["agenda"]), agora, {"clima": False}, [])
    assert set(sem_gmail) == {"agenda", "lembretes"}


def test_montar_as_fontes_nao_chama_nada_nem_marca_lembretes(monkeypatch):
    marcados = []
    monkeypatch.setattr(briefing.reminders, "mark_notified", lambda ids: marcados.extend(ids))
    conexoes = _ConexoesFalsas(["agenda"])
    item = {"id": 7, "texto": "regar as plantas", "data": "2026-10-31", "hora": "10:00"}
    fontes = briefing.sources(conexoes, dt.datetime(2026, 10, 31, 9, 0), {}, [item])
    assert conexoes.chamadas == [] and marcados == []
    assert "regar as plantas" in fontes["lembretes"]()
    assert marcados == []
