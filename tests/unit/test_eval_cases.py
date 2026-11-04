"""O conjunto de avaliação de ferramentas cumpre o tamanho e a separação prometidos."""

from collections import Counter

from tests.eval.tool_cases import CASES, VALIDATION


def test_tamanho_e_categorias():
    by_category = Counter(c.category for c in CASES)
    assert len(CASES) >= 120
    assert len(by_category) == 8 and min(by_category.values()) >= 5      # the 8th: actions on the PC


def test_validacao_nao_repete_frases_do_ajuste():
    # Frase de validação igual a uma de ajuste mediria o que já foi ajustado.
    tuning = {(c.phrase, c.camera) for c in CASES}
    assert not [c.phrase for c in VALIDATION if (c.phrase, c.camera) in tuning]
