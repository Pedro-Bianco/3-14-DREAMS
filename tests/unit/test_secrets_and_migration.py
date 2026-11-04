"""Segredos com DPAPI e migração do layout antigo, numa pasta temporária."""

import json

import pytest

from pidreams.core import paths


@pytest.fixture
def temp_data(tmp_path, monkeypatch):
    folder = tmp_path / "PIDreams"
    monkeypatch.setattr(paths, "user_data_dir", lambda: folder)
    return folder


def test_segredo_fica_cifrado_e_volta_igual(temp_data):
    from pidreams.core import secrets

    secrets.set("API_KEY", "valor-de-teste-123")  # gitleaks:allow (valor fictício)
    assert secrets.get("API_KEY") == "valor-de-teste-123"
    assert b"valor-de-teste-123" not in paths.secrets_file().read_bytes()
    secrets.delete("API_KEY")
    assert secrets.get("API_KEY") is None


def test_migracao_copia_tudo_sem_apagar_a_origem(temp_data, tmp_path, monkeypatch):
    from pidreams.core import migrate_legacy
    from pidreams.core.settings import Settings

    st = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(migrate_legacy, "SETTINGS", st)

    source_dir = tmp_path / "app_antigo"
    (source_dir / "data" / "collection" / "pi_dreams_ltm").mkdir(parents=True)
    (source_dir / "data" / "collection" / "pi_dreams_ltm" / "storage.sqlite").write_text("x")
    (source_dir / "data" / "meta.json").write_text("{}")
    (source_dir / "allowed_apps.json").write_text(json.dumps({"enabled": True, "apps": {"calc": True, "cmd": False}}))

    assert migrate_legacy.migrate(source_dir) is True
    assert (paths.qdrant_dir() / "collection" / "pi_dreams_ltm" / "storage.sqlite").is_file()
    assert st.get("apps.restrict") is True
    assert st.get("apps.items") == {"calc": True, "cmd": False}
    assert st.get("llm.model") == "qwen2.5:14b"
    assert (source_dir / "allowed_apps.json").is_file() and (source_dir / "data" / "meta.json").is_file()

    assert migrate_legacy.migrate(source_dir) is False           # roda uma vez só
