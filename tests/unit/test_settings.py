"""settings.json: defaults, valores inválidos, chaves desconhecidas e gravação."""

import json

from pidreams.core.settings import DEFAULTS, Settings


def test_sem_arquivo_usa_os_padroes(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s.data == DEFAULTS
    assert s.get("audio.volume") == 1.0


def test_valor_invalido_volta_ao_padrao(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "audio": {"volume": 7, "input_device": "Microfone USB"},
        "ollama": {"timeout_s": "rápido"},
        "first_run_done": "sim",
        "treatment": "Ana",
    }), encoding="utf-8")
    s = Settings(path)
    assert s.get("audio.volume") == 1.0             # fora da faixa
    assert s.get("audio.input_device") == "Microfone USB"
    assert s.get("ollama.timeout_s") == 600.0       # tipo errado
    assert s.get("first_run_done") is False         # bool não aceita texto
    assert s.get("treatment") == "Ana"


def test_chave_desconhecida_e_json_quebrado_nao_derrubam(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"inventado": 1, "audio": {"eco": True}}), encoding="utf-8")
    assert "inventado" not in Settings(path).data
    path.write_text("{ isto não é json", encoding="utf-8")
    assert Settings(path).data == DEFAULTS


def test_salvar_e_atomico_e_avisa_os_ouvintes(tmp_path):
    path = tmp_path / "sub" / "settings.json"
    s = Settings(path)
    seen = []
    s.subscribe(lambda st: seen.append(st.get("weather.city")))
    s.set("weather.city", "Curitiba")
    s.save()
    assert seen == ["Curitiba"]
    assert not path.with_suffix(".json.tmp").exists()
    assert Settings(path).get("weather.city") == "Curitiba"


def test_o_log_nao_guarda_o_que_foi_dito_por_padrao(tmp_path, monkeypatch):
    """Até 2026-11-09 o log guardava toda transcrição, inclusive de outras pessoas na sala."""
    from pidreams.core import logging_setup, settings

    s = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(settings, "SETTINGS", s)
    assert s.get("privacy.log_speech") is False
    assert logging_setup.said("me lembra de pagar a conta") == "[texto oculto]"
    s.set("privacy.log_speech", True)
    assert logging_setup.said("me lembra de pagar a conta") == "me lembra de pagar a conta"


def test_tema_aceita_neon_e_vidro_e_volta_ao_neon_se_invalido(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "vidro"}), encoding="utf-8")
    assert Settings(path).get("theme") == "vidro"
    path.write_text(json.dumps({"theme": "transparente"}), encoding="utf-8")
    assert Settings(path).get("theme") == "neon"
