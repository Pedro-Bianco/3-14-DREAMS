"""Chamada de ferramenta escrita no texto vira chamada de verdade e não é falada."""

import asyncio
from types import SimpleNamespace

from pidreams.agent import llm

VISIBLE = {"clipboard_read", "web_search", "open_app"}


def test_formatos_vistos_e_comuns():
    assert llm._calls_in_text('_icall_function("clipboard_read", {})', VISIBLE) == [("clipboard_read", {})]
    assert llm._calls_in_text('<tool_call>{"name": "web_search", "arguments": {"query": "dólar"}}</tool_call>',
                                  VISIBLE) == [("web_search", {"query": "dólar"})]
    assert llm._calls_in_text('clipboard_read()\nweb_search({"query": "sopa"})', VISIBLE) == [
        ("clipboard_read", {}), ("web_search", {"query": "sopa"})]


def test_fala_normal_e_ferramenta_invisivel_nao_viram_chamada():
    assert llm._calls_in_text("Abri a calculadora para você.", VISIBLE) == []
    assert llm._calls_in_text("ver_camera()", VISIBLE) == []      # câmera desligada


def test_turno_executa_e_nao_fala_o_codigo(monkeypatch):
    replies = iter([
        SimpleNamespace(message=SimpleNamespace(content='_icall_function("clipboard_read", {})', tool_calls=None)),
        SimpleNamespace(message=SimpleNamespace(content="Você copiou um convite.", tool_calls=None)),
    ])
    executed = []
    monkeypatch.setattr(llm.ollama, "Client", lambda **_kw: SimpleNamespace(chat=lambda **_k: next(replies)))
    monkeypatch.setattr(llm, "dispatch_tool", lambda name, args: executed.append(name) or "convite")
    agent = llm.LLMAgent(system_prompt="teste")

    async def turn():
        return [f async for f in agent.chat_streaming("O que eu copiei?")]

    assert asyncio.run(turn()) == ["Você copiou um convite."]
    assert executed == ["clipboard_read"]


def test_prompt_leva_a_data_de_hoje_e_marca_uso_de_ferramenta(monkeypatch):
    from pidreams.core.text import today_in_words

    replies = iter([
        SimpleNamespace(message=SimpleNamespace(content='clipboard_read()', tool_calls=None)),
        SimpleNamespace(message=SimpleNamespace(content="Pronto.", tool_calls=None)),
        SimpleNamespace(message=SimpleNamespace(content="Oi!", tool_calls=None)),
    ])
    requests_list = []
    monkeypatch.setattr(llm.ollama, "Client", lambda **_kw: SimpleNamespace(
        chat=lambda **k: requests_list.append([dict(m) for m in k["messages"]]) or next(replies)))
    monkeypatch.setattr(llm, "dispatch_tool", lambda name, args: "convite")
    agent = llm.LLMAgent()

    async def turn(phrase):
        return [f async for f in agent.chat_streaming(phrase)]

    asyncio.run(turn("O que eu copiei?"))
    assert today_in_words() in requests_list[0][0]["content"]          # no prompt do sistema
    assert requests_list[0][-1]["content"] == "O que eu copiei?"          # a mensagem fica limpa
    assert agent.used_tool is True
    asyncio.run(turn("Oi"))
    assert agent.used_tool is False


def _streaming_client(monkeypatch, chunks_per_call):
    """A fake Ollama that answers in chunks, like stream=True."""
    calls = iter(chunks_per_call)

    def chat(**kwargs):
        return iter([SimpleNamespace(message=SimpleNamespace(content=c, tool_calls=None)) for c in next(calls)])
    monkeypatch.setattr(llm.ollama, "Client", lambda **_kw: SimpleNamespace(chat=chat))


def test_primeira_frase_sai_antes_do_fim_da_resposta(monkeypatch):
    _streaming_client(monkeypatch, [["Boa ", "noite, senhor. ", "Todos os ", "sistemas estão ", "ok."]])
    agent = llm.LLMAgent(system_prompt="teste")
    seen = []

    async def turn():
        async for sentence in agent.chat_streaming("Tudo bem?"):
            seen.append((sentence, len(seen)))
    asyncio.run(turn())
    assert [s for s, _ in seen] == ["Boa noite, senhor.", "Todos os sistemas estão ok."]
    assert agent.history[-1] == {"role": "assistant", "content": "Boa noite, senhor. Todos os sistemas estão ok."}


def test_resposta_em_outra_lingua_nao_e_falada_e_e_pedida_de_novo(monkeypatch):
    calls = iter([
        iter([SimpleNamespace(message=SimpleNamespace(content="คณะกรรมการทำงาน ของคุณ. ", tool_calls=None))]),
        SimpleNamespace(message=SimpleNamespace(content="Tudo certo por aqui.", tool_calls=None)),
    ])
    monkeypatch.setattr(llm.ollama, "Client", lambda **_kw: SimpleNamespace(chat=lambda **k: next(calls)))
    agent = llm.LLMAgent(system_prompt="teste")

    async def turn():
        return [s async for s in agent.chat_streaming("Tudo bem?")]
    assert asyncio.run(turn()) == ["Tudo certo por aqui."]


def test_codigo_em_streaming_nao_e_falado(monkeypatch):
    replies = iter([
        iter([SimpleNamespace(message=SimpleNamespace(content=c, tool_calls=None))
              for c in ('_icall_function("clip', 'board_read", {})')]),
        iter([SimpleNamespace(message=SimpleNamespace(content="Você copiou um convite.", tool_calls=None))]),
    ])
    monkeypatch.setattr(llm.ollama, "Client", lambda **_kw: SimpleNamespace(chat=lambda **k: next(replies)))
    monkeypatch.setattr(llm, "dispatch_tool", lambda name, args: "convite")
    agent = llm.LLMAgent(system_prompt="teste")

    async def turn():
        return [s async for s in agent.chat_streaming("O que eu copiei?")]
    assert asyncio.run(turn()) == ["Você copiou um convite."]


def test_frase_ja_falada_nao_volta_quando_outra_lingua_aparece(monkeypatch):
    _streaming_client(monkeypatch, [["Claro, posso ajudar com isso agora mesmo. Vamos ver os detalhes juntos. "
                                     "你好世界你好世界. "]])
    agent = llm.LLMAgent(system_prompt="teste")

    async def turn():
        return [s async for s in agent.chat_streaming("Tudo bem?")]
    assert asyncio.run(turn()) == ["Claro, posso ajudar com isso agora mesmo.", "Vamos ver os detalhes juntos."]


def test_lista_sem_ponto_final_sai_item_a_item(monkeypatch):
    _streaming_client(monkeypatch, [["As manchetes:\n- Chuva forte no ", "litoral (Agência Exemplo)\n- Feira de ",
                                     "livros abre hoje (Jornal Exemplo)"]])
    agent = llm.LLMAgent(system_prompt="teste")
    seen = []

    async def turn():
        async for sentence in agent.chat_streaming("Notícias?"):
            seen.append(sentence)
    asyncio.run(turn())
    assert seen == ["As manchetes:", "- Chuva forte no litoral (Agência Exemplo)", "- Feira de livros abre hoje (Jornal Exemplo)"]
