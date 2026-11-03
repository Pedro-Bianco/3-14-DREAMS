"""Server turn.

A server's tools do not fit in the main conversation (files: 1,859 tokens, browser:
3,952, out of 4,096). So the main conversation sees only `usar_<id>`, and this short
conversation gets the request and the server's tools, runs them and returns a summary.
"""

import json
import logging
from pathlib import Path
from typing import Callable

import ollama

from pidreams.core.config import CONFIG
from pidreams.core.text import now_in_words
from pidreams.mcp.connections import Connections, Tool

log = logging.getLogger(__name__)

ROUNDS = 6
_TASK = (
    "Você executa o pedido usando as ferramentas e, no fim, responde em português, em até 3 "
    "frases, o que fez ou encontrou. Não invente resultados: use só o que as ferramentas "
    "devolverem. Se uma ação não for autorizada, não tente de novo; diga que não foi feita."
)
def _short(value) -> str:
    """A path becomes just the name: the full path pushed the CONFIRMAR/CANCELAR buttons out of
    the notice bar (seen in the real app)."""
    text = str(value)
    if ("\\" in text or "/" in text) and not text.startswith("http"):
        text = Path(text.rstrip("\\/")).name or text
    return text if len(text) <= 60 else text[:57] + "..."


def briefing(server_name: str, tool: str, arguments: dict) -> str:
    """What the person needs to know to confirm, in up to 160 characters."""
    values = " → ".join(_short(v) for v in arguments.values() if isinstance(v, (str, int, float)))
    text = f"{server_name}: {tool.replace('_', ' ')}" + (f" — {values}" if values else "")
    return text if len(text) <= 160 else text[:157] + "..."


def _answer(client, messages, schemas):
    """One call to the model; if Ollama aborts on repetition, retries once with a little
    temperature (at 0 the same input would repeat the same way). None if it fails again."""
    for temperature in (None, 0.3):
        options = CONFIG.ollama_options if temperature is None else {**CONFIG.ollama_options, "temperature": temperature}
        try:
            return client.chat(model=CONFIG.ollama_model, messages=messages, tools=schemas, options=options,
                                think=False, keep_alive=CONFIG.ollama_keep_alive).message
        except ollama.ResponseError as e:
            log.warning(f"[MCP] server turn: {e}")
    return None


def execute(connections: Connections, id_: str, name: str, request: str, instructions_for: str,
             tools: list[Tool], confirm: Callable[[str], bool]) -> str:
    from pidreams.agent.llm import _calls_in_text      # same fix as in the main conversation

    by_name = {f.name: f for f in tools}
    schemas = [{"type": "function", "function": {"name": f.name, "description": f.description,
                                                  "parameters": f.schema}} for f in tools]
    messages = [{"role": "system", "content": f"{_TASK}\n\nAgora: {now_in_words()}.\n\n{instructions_for}".strip()},
                 {"role": "user", "content": request}]
    client = ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)
    for _ in range(ROUNDS):
        msg = _answer(client, messages, schemas)
        if msg is None:
            return f"Não consegui concluir no {name} agora (o modelo travou repetindo texto)."
        text = (msg.content or "").strip()
        calls = [(tc.function.name, tc.function.arguments) for tc in msg.tool_calls or []]
        if not calls:
            calls = _calls_in_text(text, set(by_name))
            text = "" if calls else text
        if not calls:
            return text or "Pronto."
        # The text that comes with the call is kept out of the history: qwen2.5:14b sometimes
        # starts with garbage in another language ("คณะกรรม…联合国…") and, when kept, it turned into
        # endless repetition on the next round (seen in the real app).
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": n, "arguments": a}} for n, a in calls]})
        for tool, arguments in calls:
            f = by_name.get(tool)
            if f is None:
                result = f"A ferramenta {tool} não existe neste servidor."
            elif not f.read_only and not confirm(question := briefing(name, tool, arguments)):
                # End of the turn here, with a fixed sentence: asked to summarize the refusal, the model
                # answered "preciso de uma confirmação para prosseguir" (seen in the real app).
                return f"Não foi feito, porque você não confirmou ({question})."
            else:
                result = connections.call(id_, tool, arguments)
            log.info(f"[MCP] {name}.{tool}({json.dumps(arguments, ensure_ascii=False)[:120]})")
            messages.append({"role": "tool", "content": result})
    return f"Não consegui terminar no {name}: parei depois de {ROUNDS} etapas."
