"""Palavras em inglês reescritas para a voz em português (com o eSpeak de verdade, que vem no app)."""

import pytest

from pidreams.audio import english


@pytest.mark.parametrize("text, expected", [
    ("Abri o YouTube e o Spotify no Google Chrome.", "Abri o iutúbi e o ispádifai no gúgou croum."),
    ("OK, mandei o e-mail antes do deadline.", "ouquei, mandei o iméiu antes do dédi láin."),
    ("Keep It Simple", "quípi iti símpou"),
])
def test_ingles_vira_grafia_brasileira(text, expected):
    assert english.respell(text) == expected


@pytest.mark.parametrize("text", [
    "Até amanhã! O PI avisa no SUS e no CPF. Me ajuda a ver o voo?",      # acronyms, accents, "me", "voo"
    "O teatro real leem e creem; enjoo no voo para o zoo.",               # "ea", "ee", "oo" in Portuguese
    "Encontrei três compromissos na sua agenda para amanhã.",
])
def test_portugues_fica_igual(text):
    assert english.respell(text) == text


def test_sem_espeak_fala_como_esta(monkeypatch):
    def broken():
        raise OSError("no espeak")
    monkeypatch.setattr(english, "_phonemize", broken)
    assert english.respell("Abri o YouTube.") == "Abri o YouTube."          # never silence, never an error
    assert english.respell("Está online.") == "Está onláin."                  # the fixed Brazilian ones still work
