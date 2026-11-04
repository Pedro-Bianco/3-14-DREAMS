"""classify_relation entende a resposta do modelo em JSON ou como palavra solta."""

from types import SimpleNamespace

import pytest

from pidreams.memory import updater

CANDIDATE = [{"id": 7, "text": "O usuário mora em Recife", "score": 0.8}]


def _with_reply(monkeypatch, text):
    client = SimpleNamespace(chat=lambda **_kw: SimpleNamespace(message=SimpleNamespace(content=text)))
    monkeypatch.setattr(updater.ollama, "Client", lambda **_kw: client)


@pytest.mark.parametrize("text, expected", [
    ('{"action": "UPDATE"}', {"action": "UPDATE", "target_id": 7}),
    ('{"relation": "DUPLICATE"}', {"action": "DUPLICATE", "target_id": None}),   # todos a temperatura 0
    ("```json\nUPDATE\n```", {"action": "UPDATE", "target_id": 7}),   # formato real do qwen2.5:14b
    ("DUPLICATE", {"action": "DUPLICATE", "target_id": None}),
    ('{"action": "add"}', {"action": "ADD", "target_id": None}),
    ("não sei", {"action": "ADD", "target_id": None}),                  # fallback conservador
])
def test_classifica_json_ou_palavra_solta(monkeypatch, text, expected):
    _with_reply(monkeypatch, text)
    assert updater.classify_relation(CANDIDATE, "O usuário se mudou", "http://x", "m") == expected
