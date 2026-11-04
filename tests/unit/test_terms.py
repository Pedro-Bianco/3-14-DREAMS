"""Termos para a busca por palavra exata: acentos, códigos e índices estáveis."""

from pidreams.memory import terms


def test_minusculas_sem_acento_e_codigo_inteiro_e_em_pedacos():
    assert terms.tokens("Penalidade por MORA, contrato 2024-0815.") == [
        "penalidade", "por", "mora", "contrato", "2024-0815", "2024", "0815"]


def test_numeros_com_ponto_e_barra():
    assert "12.345" in terms.tokens("Nota fiscal 12.345 de 03/11")
    assert {"12", "345", "03/11", "03", "11"} <= set(terms.tokens("Nota fiscal 12.345 de 03/11"))


def test_mesmo_texto_mesmo_vetor_e_contagem_de_repeticao():
    a, b = terms.sparse("multa multa atraso"), terms.sparse("multa multa atraso")
    assert a.indices == b.indices and a.values == b.values
    assert sorted(a.values) == [1.0, 2.0]


def test_codigos_vizinhos_tem_indices_diferentes():
    assert set(terms.sparse("2024-0815").indices) != set(terms.sparse("2024-0816").indices)
