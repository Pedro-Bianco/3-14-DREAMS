"""O PI só se encerra com um pedido de saída inteiro — não por achar a palavra no meio da frase."""

import pytest

from pidreams.agent.loop import is_exit_request


@pytest.mark.parametrize("frase", ["Tchau.", "sair", "Encerrar!", "pode encerrar"])
def test_pedidos_de_saida(frase):
    assert is_exit_request(frase)


@pytest.mark.parametrize("frase", ["Eu quero desligar o PC em 5 minutos.", "fecha o Bloco de Notas",
                                   "para a música", "desliga o computador", "tchau, mas antes abre o Chrome"])
def test_acoes_no_pc_nao_encerram_o_pi(frase):
    assert not is_exit_request(frase)
