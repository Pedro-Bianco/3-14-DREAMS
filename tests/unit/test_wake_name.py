"""Answering only when called by name: the transcribed text decides."""

from pidreams.agent.wake_name import strip_name


def test_the_name_is_taken_out_of_the_request():
    for said, request in (("PI, que horas são?", "que horas são?"), ("Pi que horas são", "que horas são"),
                          ("P.I., abre a calculadora", "abre a calculadora"), ("P I, oi", "oi"),
                          ("pi, PI, toca música", "toca música"), ("P, abro o crome.", "abro o crome.")):
        assert strip_name(said, "PI dreams") == request, said


def test_speech_without_the_name_is_not_for_the_assistant():
    for said in ("Que horas são?", "abre o PI", "pião de madeira", "Carlos, vem cá", "", "Meu pai chegou.",
                 "piada boa essa", "Ih, esqueci a chave", "E aí?", "Pizza ou hambúrguer?"):
        assert strip_name(said, "PI dreams") is None, said


def test_the_name_alone_is_a_call():
    assert strip_name("PI?", "PI dreams") == ""


def test_a_custom_name_works_besides_pi():
    assert strip_name("Jarvis, toca música", "Jarvis") == "toca música"
    assert strip_name("PI, toca música", "Jarvis") == "toca música"
    assert strip_name("Sexta-feira, toca música", "Sexta-feira") == "toca música"


def test_a_call_after_someone_else_talking_counts():
    """Seen in the app: the recording held the end of another conversation before the call."""
    assert strip_name("Fazer não funciona mais, tá bom? Pi, o que você tá fazendo?", "PI dreams") ==         "o que você tá fazendo?"
    assert strip_name("Não pegue. Pi! Me fala o que você está fazendo!", "PI dreams") ==         "Me fala o que você está fazendo!"
    assert strip_name("Ele disse que vem. Depois a gente vê o PI.", "PI dreams") is None
