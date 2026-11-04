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
