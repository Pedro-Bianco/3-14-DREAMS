import logging
import re
import threading
import time

import ollama

from pidreams.core.config import CONFIG
from pidreams.memory import topics
from pidreams.memory.store import LTMStore
from pidreams.memory.updater import classify_relation

log = logging.getLogger(__name__)


# What the extractor sees and returns. Before, only the user's lines went in: a short answer
# to the assistant ("sim, desde 2019") meant nothing alone and came back NULO, and so did "vendi o
# carro" (no way to say a fact stopped being true). Now the assistant's lines go in as context and
# each line is tagged: PERFIL is always in the conversation, FATO is found by similarity, DEIXOU
# only triggers the consolidation. Example names are clearly fictitious so they are never copied.
_REFLECTION_PROMPT = """\
Abaixo está um trecho de conversa entre o USUÁRIO e o ASSISTENTE.
Extraia o que o USUÁRIO afirmou ou confirmou sobre si mesmo. Use as falas do ASSISTENTE só como
contexto (para entender um "sim" ou uma resposta curta); nunca extraia o que só o assistente disse.

Escreva um item por linha, em português, como frase completa sobre "o usuário", começando com:
PERFIL: nome, como quer ser chamado, preferências de como o assistente deve responder, instruções
FATO: outros fatos sobre o usuário (trabalho, cidade, família, animais, projetos, hobbies, rotina, datas)
DEIXOU: algo sobre o usuário que deixou de ser verdade (vendeu, se mudou, saiu, não tem mais)

Ignore pedidos e comandos (abrir programas, volume, música, pesquisas, lembretes, perguntas gerais):
não são fatos sobre o usuário. Perguntas sobre documentos e o que o assistente respondeu a partir de
documentos ou pesquisas também não são: o conteúdo de um documento não é um fato sobre o usuário.
Nunca escreva sobre ausência de informação. Se não houver nada, escreva NULO.

Exemplos:
Conversa:
USUÁRIO: me chamo Fulano Exemplo e sou engenheiro de dados
Saída:
PERFIL: O nome do usuário é Fulano Exemplo
FATO: O usuário é engenheiro de dados

Conversa:
ASSISTENTE: Você ainda mora em Cidade Exemplo?
USUÁRIO: sim, desde 2018
Saída:
FATO: O usuário mora em Cidade Exemplo desde 2018

Conversa:
USUÁRIO: me chama de chefe e responde sempre curto
Saída:
PERFIL: O usuário quer ser chamado de chefe
PERFIL: O usuário prefere respostas curtas

Conversa:
USUÁRIO: vendi minha moto semana passada
Saída:
DEIXOU: O usuário vendeu a moto e não tem mais moto

Conversa:
USUÁRIO: completei dois anos na Empresa Exemplo e meu time se chama Time Azul
Saída:
FATO: O usuário trabalha na Empresa Exemplo há dois anos
FATO: O time do usuário se chama Time Azul

Conversa:
USUÁRIO: abre o spotify e pausa a música
Saída:
NULO

Conversa:
USUÁRIO: quanto pago de multa se atrasar a mensalidade?
ASSISTENTE: Pelo documento contrato_exemplo.pdf, a multa é de 2%.
USUÁRIO: e quem assinou?
ASSISTENTE: Assinou Beltrano Exemplo, conforme o contrato_exemplo.pdf.
Saída:
NULO

Conversa:
{chat}

Saída:"""


_KINDS = {"PERFIL": "perfil", "FATO": "fato", "DEIXOU": "deixou"}
_ABOUT_USER = re.compile(r"\busu[aá]ri[oa]\b", re.IGNORECASE)


def format_chat(turns: list[dict]) -> str:
    """The conversation as the extractor reads it. The assistant's lines go in as context
    (shortened: its long answers would eat the extractor's window), so "sim, desde 2019" makes sense."""
    return "\n".join(
        f"USUÁRIO: {t['content']}" if t.get("role") == "user" else f"ASSISTENTE: {t['content'][:300]}"
        for t in turns if t.get("content"))


def parse_facts(raw: str) -> list[tuple[str, str]]:
    """[(kind, fact)] from the extractor's answer. A line without a known tag counts as a fact
    (small models sometimes drop the tag); NULO, short lines and statements of absence are dropped,
    and so are lines that are not about the user: "O líder do projeto é Fulano" came from a
    document the assistant had just quoted and was stored as a memory (app test, 2026-10-31)."""
    facts = []
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("•-– ").strip()
        tag, _, rest = line.partition(":")
        kind = _KINDS.get(tag.strip().upper())
        fact = rest.strip() if kind else line
        kind = kind or "fato"
        if len(fact) <= 10 or "nulo" in fact.lower() or _is_absence(fact) or not _ABOUT_USER.search(fact):
            continue
        facts.append((kind, fact))
    return facts


# The extractor uses the SAME model that answers the user. Since Ollama serves one
# request at a time, reflecting while the user waits puts their reply in line
# behind a whole LLM call — that caused a latency jump right after a long
# request. So reflection only runs while the agent is idle.
_busy = threading.Event()


def mark_busy() -> None:
    _busy.set()


def mark_free() -> None:
    _busy.clear()


def agent_busy() -> bool:
    return _busy.is_set()


# The prompt asks not to write about missing information, but small models slip:
# one stored "O nome do usuário não foi fornecido" as if it were a fact.
# A memory of absence is worse than no memory — it is recalled later and the
# agent starts claiming it does not know something it may already know.
_ABSENCE = (
    "não foi fornecid", "nao foi fornecid", "não informou", "nao informou",
    "não foi informad", "nao foi informad", "não há informação",
    "nao ha informacao", "não menciona", "nao menciona", "não especificad",
    "nao especificad", "desconhecid", "não sabemos", "nao sabemos",
    "não foi dito", "nao foi dito", "não consta", "nao consta",
    "sem informação", "sem informacao", "não revelou", "nao revelou",
)


def _is_absence(fact: str) -> bool:
    low = fact.lower()
    return any(marker in low for marker in _ABSENCE)


class MemoryWorker:
    def __init__(self, store: LTMStore, on_store=None):
        self._store = store
        self._on_store = on_store  # callback(fact: str) called when each fact is stored
        self._client = ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)
        self._queue: list[list[dict]] = []
        self._pending = 0                     # queued + being processed
        self._next_tagging = 0.0              # when to look for memories without a topic again
        self._lock = threading.Lock()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def submit(self, session_buffer: list[dict]):
        if len(session_buffer) < 2:
            return
        log.info(f"[LTM] submit received — {len(session_buffer)} turns in the buffer")
        with self._lock:
            self._queue.append(list(session_buffer))
            self._pending += 1

    def drain(self, timeout: float) -> bool:
        """Waits for the queue to empty. The thread is a daemon: closing the app used to kill it
        mid-reflection, so what was said right before closing was never stored."""
        until = time.time() + timeout
        while time.time() < until:
            with self._lock:
                if self._pending == 0:
                    return True
            time.sleep(0.2)
        log.warning("[LTM] Closing with reflection still pending")
        return False

    def _run(self):
        while True:
            time.sleep(0.5)
            if agent_busy():
                continue                      # waits until the user has been answered
            with self._lock:
                batch, self._queue = self._queue[:], []
            for turns in batch:
                try:
                    self._process(turns)
                except Exception as e:
                    log.warning(f"[MemoryWorker] Error: {e}")
                finally:
                    with self._lock:
                        self._pending -= 1
            if not batch and time.time() >= self._next_tagging and not agent_busy():
                self._tag_topics()

    def _tag_topics(self) -> None:
        """Gives a topic to memories that have none (new ones, and the ones saved before topics
        existed), one batch per idle moment. Memories added from the panel are caught too, since
        the store is read again instead of tracking what this worker saved."""
        self._next_tagging = time.time() + 60
        try:
            pending = self._store.untagged()
            profile = {m["id"]: topics.PROFILE for m in pending if m["kind"] == "perfil"}
            if profile:
                self._store.set_topics(profile)
            facts = [m for m in pending if m["kind"] != "perfil"][:topics.BATCH]
            if not facts:
                return
            resp = self._client.chat(
                model=CONFIG.ollama_model,
                messages=[{"role": "user", "content": topics.prompt_for([m["text"] for m in facts])}],
                options=CONFIG.ollama_options, think=False, keep_alive=CONFIG.ollama_keep_alive)
            found = topics.parse_topics(resp.message.content, len(facts))
            self._store.set_topics({m["id"]: t for m, t in zip(facts, found)})
            log.info(f"[LTM] Topics given to {len(facts)} memories")
            if len(pending) - len(profile) > len(facts):
                self._next_tagging = time.time() + 5     # more left: next idle moment, not in a minute
        except Exception as e:
            log.warning(f"[LTM] Topic tagging failed (retrying later): {e}")

    def _process(self, turns: list[dict]):
        if not any(t.get("role") == "user" and t.get("content") for t in turns):
            log.warning("[LTM] No user line in the window — dropped")
            return
        chat = format_chat(turns)
        log.info(f"[LTM] Reflecting on {len(turns)} turns...")
        resp = self._client.chat(
            model=CONFIG.ollama_model,
            messages=[{"role": "user", "content": _REFLECTION_PROMPT.format(chat=chat)}],
            # Same options as the agent: a different num_ctx would make Ollama reload the model.
            options=CONFIG.ollama_options,
            think=False,
            keep_alive=CONFIG.ollama_keep_alive,
        )
        raw = resp.message.content.strip()
        log.info(f"[LTM] Model returned: {raw[:200]!r}")
        facts = parse_facts(raw)
        if not facts:
            log.info("[LTM] Nothing relevant — dropped")
            return
        for kind, fact in facts:
            if kind == "deixou":
                self._forget(fact)
                continue
            stored = self._smart_upsert(fact, kind)
            if stored:
                log.info(f"[LTM] Stored: {fact[:70]}")
                if self._on_store:
                    try:
                        self._on_store(fact)
                    except Exception:
                        pass

    def _forget(self, fact: str) -> None:
        """Something stopped being true: update or delete the memory it contradicts. With nothing to
        contradict, it is kept as a fact ("vendeu a moto" still says something about the user)."""
        candidates = self._store.search_candidates(fact, threshold=CONFIG.ltm_update_threshold)
        result = classify_relation(candidates, fact, CONFIG.ollama_host, CONFIG.ollama_model) if candidates else {"action": "ADD"}
        log.info(f"[LTM] change → {result['action']} (candidates: {len(candidates)})")
        if result["action"] in ("UPDATE", "DELETE") and result.get("target_id") is not None:
            self._store.delete_one(result["target_id"])
            if result["action"] == "DELETE":
                return
        if result["action"] != "DUPLICATE":
            self._store.upsert(fact, dedup_threshold=1.0, kind="fato")

    def _smart_upsert(self, fact: str, kind: str = "fato") -> bool:
        """Stores the fact, replacing or deleting contradicted memories when smart update is on."""
        if not CONFIG.ltm_smart_update:
            return self._store.upsert(fact, kind=kind)

        candidates = self._store.search_candidates(
            fact, threshold=CONFIG.ltm_update_threshold)

        # Duplicate zone — upsert would block it anyway, but we get ahead of it
        if any(c["score"] >= 0.96 for c in candidates):
            log.warning(f"[LTM] Early duplicate — dropped: {fact[:60]}")
            return False

        # Update zone — asks the LLM to classify
        if candidates:
            result = classify_relation(
                candidates, fact, CONFIG.ollama_host, CONFIG.ollama_model)
            action = result["action"]
            log.info(f"[LTM] classify_relation → {action} (candidates: {len(candidates)})")

            if action == "DUPLICATE":
                return False
            if action in ("UPDATE", "DELETE") and result.get("target_id") is not None:
                if self._store.delete_one(result["target_id"]):
                    log.info(f"[LTM] Memory {'replaced' if action == 'UPDATE' else 'deleted'} (id={result['target_id']})")
            # classify_relation already validated — skips upsert's internal dedup
            return self._store.upsert(fact, dedup_threshold=1.0, kind=kind)

        return self._store.upsert(fact, kind=kind)
