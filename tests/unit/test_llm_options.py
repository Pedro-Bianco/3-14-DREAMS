"""Toda chamada ao modelo de conversa usa temperatura 0, teto de resposta e think=False.

Sem o teto, a temperatura 0 já levou o qwen3:8b a repetir até o timeout; sem think=False,
o qwen3 raciocina por padrão e o raciocínio iria para a fala.
"""

import asyncio
from types import SimpleNamespace

from pidreams.core.config import CONFIG


class _FakeClient:
    def __init__(self, **_kw):
        self.calls = []

    def chat(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(message=SimpleNamespace(content="NULO", tool_calls=None))


def _check(kw):
    assert kw["options"]["temperature"] == 0
    assert kw["options"]["num_predict"] == CONFIG.ollama_num_predict
    assert kw["options"]["num_ctx"] == CONFIG.ollama_num_ctx
    assert kw["options"]["use_mmap"] is False        # 8,1 GB → 0,6 GB de RAM com o modelo na GPU
    assert kw["think"] is False


def test_agente_resposta_e_aquecimento(monkeypatch):
    from pidreams.agent import llm

    monkeypatch.setattr(llm.ollama, "Client", _FakeClient)
    agent = llm.LLMAgent(system_prompt="teste")
    asyncio.run(agent._call_llm())
    asyncio.run(agent.warmup())
    assert len(agent._client.calls) == 2
    for kw in agent._client.calls:
        _check(kw)


def test_memoria_classificacao_e_reflexao(monkeypatch):
    from pidreams.memory import updater, worker

    client = _FakeClient()
    monkeypatch.setattr(updater.ollama, "Client", lambda **_kw: client)
    updater.classify_relation([{"id": 1, "text": "fato", "score": 0.9}], "fato novo", "http://x", "m")

    reflector = object.__new__(worker.MemoryWorker)      # sem a thread do __init__
    reflector._client = client
    reflector._process([{"role": "user", "content": "Eu moro em Recife."},
                       {"role": "assistant", "content": "Anotado."}])
    assert len(client.calls) == 2
    for kw in client.calls:
        _check(kw)
