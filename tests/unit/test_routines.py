"""Routines: which phrases start them, validation, and running steps that fail."""

import copy

from pidreams import routines

SAMPLE = copy.deepcopy(routines.EXAMPLES) + [
    {"name": "jogo", "steps": [{"type": "falar", "value": "Bom jogo."}]},
    {"name": "jogo online", "steps": [{"type": "falar", "value": "Boa partida."}]},
]


def test_short_commands_start_a_routine():
    for said, name in (("modo trabalho", "trabalho"), ("Ativar protocolo foco.", "foco"),
                       ("rotina trabalho", "trabalho"), ("iniciar a rotina de foco", "foco"),
                       ("Modo Trabalho!", "trabalho")):
        assert routines.find(said, SAMPLE)["name"] == name, said


def test_the_longest_name_wins():
    assert routines.find("protocolo jogo online", SAMPLE)["name"] == "jogo online"
    assert routines.find("protocolo jogo", SAMPLE)["name"] == "jogo"


def test_questions_and_unknown_names_do_not_start_anything():
    for said in ("o que a rotina trabalho faz?", "modo festa", "trabalho", "modo monitoramento"):
        assert routines.find(said, SAMPLE) is None, said


def test_examples_are_valid_and_problems_are_explained():
    assert routines.problem(routines.EXAMPLES) is None
    assert "modo do PI" in routines.problem([{"name": "Monitoramento", "steps": [{"type": "falar", "value": "a"}]}])
    assert "duas rotinas" in routines.problem([{"name": "a", "steps": [{"type": "falar", "value": "x"}]},
                                              {"name": "A", "steps": [{"type": "falar", "value": "y"}]}])
    assert "1 a 20 passos" in routines.problem([{"name": "vazia", "steps": []}])
    assert "volume" in routines.problem([{"name": "v", "steps": [{"type": "volume", "value": "200"}]}])
    assert "desconhecido" in routines.problem([{"name": "v", "steps": [{"type": "voar", "value": "x"}]}])


def test_a_failed_step_does_not_stop_the_others():
    done = []
    actions = {
        "abrir": lambda v: f"Não encontrei um programa ou arquivo chamado '{v}'. Nada foi aberto.",
        "fechar": lambda v: "Cancelado pelo usuário: nada foi feito.",
        "volume": lambda v: done.append(("volume", v)) or f"Volume em {v}%.",
        "silenciar": lambda v: 1 / 0,
        "musica": lambda v: done.append(("musica", v)) or "Mandei pausar o que está tocando.",
        "falar": lambda v: done.append(("falar", v)) or "Falei.",
    }
    routine = {"name": "teste", "steps": [
        {"type": "abrir", "value": "programa-que-nao-existe"}, {"type": "volume", "value": "30"},
        {"type": "fechar", "value": "editor"}, {"type": "silenciar", "value": "sim"},
        {"type": "musica", "value": "pausar"}, {"type": "falar", "value": "Pronto."}]}
    summary = routines.run(routine, actions)
    assert done == [("volume", "30"), ("musica", "pausar"), ("falar", "Pronto.")]
    assert summary.startswith("Rotina teste: 3 de 6 passos feitos.")
    assert "programa-que-nao-existe" in summary and "editor" in summary and "silenciar" in summary


def test_all_steps_done():
    summary = routines.run({"name": "foco", "steps": [{"type": "falar", "value": "Oi."}]}, {"falar": lambda v: "Falei."})
    assert summary == "Rotina foco: tudo feito."
