"""Emojis saem da voz e do chat (regra de conduta)."""

from pidreams.core.text import remove_emojis


def test_remove_emojis_sem_deixar_espaco_duplo():
    assert remove_emojis("Pronto, senhor! 😊 Abri a calculadora 🧮✨") == "Pronto, senhor! Abri a calculadora "
    assert remove_emojis("Sem emoji, sem mudança.") == "Sem emoji, sem mudança."


def test_datas_por_extenso():
    import datetime as dt

    from pidreams.core.text import now_in_words, date_in_words

    assert date_in_words(dt.date(2026, 10, 30)) == "sexta, 30 de outubro"
    assert date_in_words(dt.date(2026, 10, 31), year=True) == "sábado, 31 de outubro de 2026"
    assert now_in_words(dt.datetime(2026, 10, 30, 9, 5)) == (
        "sexta-feira, 30 de outubro de 2026 (amanhã é sábado, 31 de outubro), agora são 09:05")
