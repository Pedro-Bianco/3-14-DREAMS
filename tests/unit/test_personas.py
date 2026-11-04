"""Personas: prompt montado, regras comuns a todas e tratamento configurável."""

import pytest

from pidreams.agent.personas import conduct
from pidreams.core.settings import Settings


@pytest.fixture
def st(tmp_path):
    return Settings(tmp_path / "settings.json")


def test_tres_personas_com_campos_obrigatorios():
    personas = conduct.list_items()
    assert {p["id"] for p in personas} == {"espirituoso", "amigavel", "formal"}
    for p in personas:
        assert {"id", "name", "description", "example_line", "style"} <= p.keys()
        assert "{tratamento}" in p["example_line"]


@pytest.mark.parametrize("persona", ["espirituoso", "amigavel", "formal"])
def test_regras_de_conduta_valem_para_todas(st, persona):
    st.set("persona_id", persona)
    prompt = conduct.build_prompt(st)
    assert conduct.CONDUCT_RULES in prompt
    assert conduct.load(persona)["style"] in prompt


def test_tratamento_e_nome_configuraveis(st):
    st.set("treatment", "Ana")
    st.set("assistant_name", "Sexta-feira")
    prompt = conduct.build_prompt(st)
    assert 'Chame o usuário de "Ana"' in prompt and "Você é Sexta-feira" in prompt
    st.set("treatment", "")
    assert "Não use um vocativo fixo" in conduct.build_prompt(st)


def test_frase_de_exemplo_sem_tratamento_fica_natural():
    formal = conduct.load("formal")
    assert conduct.sample_phrase(formal, "Ana") == "Certamente, Ana. A calculadora foi aberta."
    assert conduct.sample_phrase(formal, "") == "Certamente. A calculadora foi aberta."


def test_persona_inexistente_cai_na_padrao():
    assert conduct.load("nao-existe")["id"] == conduct.DEFAULT_PERSONA
