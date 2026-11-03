"""
classify_relation — decides what a new fact does to the most similar memories (up to 3).

Returns a dict with:
  {"action": "ADD"}                         — new and complementary: store it
  {"action": "DUPLICATE"}                   — already captured: drop it
  {"action": "UPDATE", "target_id": <id>}   — replaces that memory (same subject, new value)
  {"action": "DELETE", "target_id": <id>}   — that memory is no longer true and nothing replaces it

The ADD/UPDATE/DELETE/NOOP set is the one long-term memory tools like mem0 use. Before v0.4.0 only the
top-1 candidate was compared and nothing could be deleted: "vendi o carro" left "tem um carro"
standing forever.

Conservative fallback on any failure: {"action": "ADD"} — never deletes by accident.
"""

import logging
import re

import ollama

from pidreams.core.config import CONFIG

log = logging.getLogger(__name__)

_MAX_CANDIDATES = 3

_PROMPT = """\
Você é um gerenciador de memória sobre o usuário. Compare o NOVO FATO com as memórias existentes.

Memórias existentes:
{memories}

Novo fato: "{new_fact}"

Responda com UMA linha:
ADD          → o novo fato é complementar ou de outro assunto (todas as memórias continuam valendo).
DUPLICATE    → o novo fato já está numa das memórias, mesmo com outras palavras.
UPDATE n     → o novo fato substitui a memória [n]: mesmo assunto, valor novo.
DELETE n     → a memória [n] deixou de ser verdade e o novo fato só diz isso, sem valor novo.

Exemplos:
[1] "O usuário mora em Recife" + "O usuário se mudou para Salvador" → UPDATE 1
[1] "O usuário tem um carro" + "O usuário vendeu o carro" → DELETE 1
[1] "O usuário é professor" + "O usuário dá aulas de história" → UPDATE 1
[1] "O usuário gosta de surfar" + "O usuário curte surfe" → DUPLICATE
[1] "O usuário tem uma gata chamada Mel" + "O usuário trabalha como enfermeiro" → ADD

Na dúvida, responda ADD — é melhor guardar duas memórias parecidas do que apagar uma válida.

Resposta:"""

_FALLBACK = {"action": "ADD", "target_id": None}


def classify_relation(candidates: list[dict], new_fact: str, ollama_host: str, model: str) -> dict:
    """Compares new_fact with the top candidates. Always returns a safe dict — never raises."""
    candidates = candidates[:_MAX_CANDIDATES]
    if not candidates:
        return dict(_FALLBACK)
    memories = "\n".join(f'[{i}] "{c["text"]}"' for i, c in enumerate(candidates, 1))
    try:
        client = ollama.Client(host=ollama_host, timeout=CONFIG.ollama_timeout_s)
        resp = client.chat(
            model=model,
            messages=[{"role": "user", "content": _PROMPT.format(memories=memories, new_fact=new_fact)}],
            options=CONFIG.ollama_options, think=False, keep_alive=CONFIG.ollama_keep_alive)
        return parse_decision(resp.message.content, candidates)
    except Exception as e:
        log.warning(f"[LTM] classify_relation error: {e}")
        return dict(_FALLBACK)


def parse_decision(raw: str, candidates: list[dict]) -> dict:
    """The word counts, whatever the shape ("UPDATE 2", "```json {"action": "DELETE", "n": 1}```"…):
    requiring a JSON key once made every answer fall into ADD (measured: 0/3)."""
    text = (raw or "").upper()
    word = re.search(r"\b(UPDATE|DELETE|DUPLICATE|ADD)\b", text)
    if not word:
        return dict(_FALLBACK)
    action = word.group(1)
    if action in ("ADD", "DUPLICATE"):
        return {"action": action, "target_id": None}
    number = re.search(r"\b(\d)\b", text[word.end():]) or re.search(r"\[(\d)\]", text)
    index = int(number.group(1)) - 1 if number else (0 if len(candidates) == 1 else -1)
    if not 0 <= index < len(candidates):
        return dict(_FALLBACK)                 # which memory? unclear: never delete by guess
    log.info(f"[LTM] classify_relation {action} → id={candidates[index]['id']}")
    return {"action": action, "target_id": candidates[index]["id"]}
