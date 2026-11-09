import datetime as dt
import json
import logging
import re
import asyncio
import threading
from typing import AsyncGenerator
import ollama
from pidreams.agent.tools import active_tool_schemas, dispatch_tool
from pidreams.agent.personas.conduct import build_prompt
from pidreams.core.config import CONFIG
from pidreams.core.logging_setup import said
from pidreams.core.settings import SETTINGS

log = logging.getLogger(__name__)


def system_prompt() -> str:
    """Prompt of the persona chosen in the settings (personas/conduct.py)."""
    return build_prompt(SETTINGS)


# A line break also ends a sentence: a list of headlines has no full stops, and spoken as one
# "sentence" it waited 9.4 s for the voice to synthesize the whole list (2026-11-04).
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$|\s*\n\s*')


def _split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_RE.split(text.strip()) if p.strip()]


def _calls_in_text(text: str, visible: set[str]) -> list[tuple[str, dict]]:
    """Calls the model wrote in the text instead of using the proper field.

    Seen on qwen2.5:14b at temperature 0: '_icall_function("clipboard_read", {})' came out
    as the reply and would have been spoken. A tool name is an English
    identifier: in Portuguese speech it only shows up when it is code.
    The arguments are the first JSON object after the name, on the same line.
    """
    calls = []
    for name in sorted(visible):
        position = text.find(name)
        if position < 0:
            continue
        args: dict = {}
        rest = text[position + len(name):].split("\n", 1)[0]
        start_at = rest.find("{")
        if start_at >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(rest[start_at:])
                if isinstance(obj, dict):
                    args = obj.get("arguments", obj) if "name" in obj else obj
            except ValueError:
                pass
        calls.append((position, name, args))
    return [(name, args) for _, name, args in sorted(calls)]


_SENTENCE_END_RE = re.compile(r"[.!?]+(?=\s)|\n")


def _complete_sentences_end(text: str, start: int) -> int:
    """Where the last finished sentence of text[start:] ends (a . ! or ? followed by a space, or a
    line break), or start when none is finished yet. The last sentence of a reply has no space after it: it is
    said when the reply ends."""
    end = start
    for match in _SENTENCE_END_RE.finditer(text, start):
        end = match.end()
    return end


def _looks_like_code(text: str, visible: set[str]) -> bool:
    """A reply that starts like code or names a tool is a call written as text: never spoken."""
    stripped = text.lstrip()
    return stripped[:1] in ("{", "[", "<", "`", "_") or any(name in text for name in visible)


def _foreign_script(text: str) -> bool:
    """Most letters outside the Latin script (Thai, Chinese...): not an answer in Portuguese."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 8 and sum(ord(c) > 0x24F for c in letters) > len(letters) * 0.3


class LLMAgent:
    def __init__(self, system_prompt: str | None = None, tools=None, dispatch=None):
        """The tool list is resolved on every call, so turning a service or connection
        on/off in the panel applies to the next message without recreating the agent.
        tools/dispatch: an agent with its own tools (the monitor); None = the app's tools."""
        self._tools, self._dispatch = tools, dispatch
        self._client = ollama.Client(host=CONFIG.ollama_host, timeout=CONFIG.ollama_timeout_s)
        self.history: list[dict] = [
            {"role": "system", "content": system_prompt or build_prompt(SETTINGS)}
        ]
        self._fixed_prompt = system_prompt is not None
        self._day = dt.date.today()
        if system_prompt is None:
            # Persona, name or form of address changed in the settings apply from the
            # next message on, without recreating the agent.
            SETTINGS.subscribe(lambda st: self.history[0].update(content=build_prompt(st)))

    def _tool_schemas(self) -> list[dict]:
        return self._tools() if self._tools else active_tool_schemas()

    def _refresh_date(self):
        """Today's date lives in the system prompt (build_prompt); with the app open past
        midnight, it is rebuilt once on the new day."""
        if not self._fixed_prompt and dt.date.today() != self._day:
            self._day = dt.date.today()
            self.history[0]["content"] = build_prompt(SETTINGS)

    def _camera_hint(self) -> str:
        """Only with the camera on and in the local panel. Without this notice next to the
        request, the model treated 'como eu estou?' and 'quantos dedos?' as small talk
        and answered without looking (measured: 6 of 8 → see the test)."""
        from pidreams.agent.tools import is_service_enabled

        if not is_service_enabled("camera"):
            return ""
        return (
            "[CÂMERA LIGADA] A webcam está apontada para o usuário. Se a resposta "
            "depender do que ela mostra (ele, a aparência, roupa, gestos, dedos, "
            "objetos, papéis, o ambiente), chame ver_camera ANTES de responder. "
            "Se não depender (clima, filmes, notícias, conhecimento geral, "
            "lembretes, conversa), NÃO use a câmera."
        )

    def _build_user_content(self, user_text: str, recall: list[str], kb: list[str],
                            profile: list[str] | None = None) -> str:
        """ORDER matters and was measured: this model weighs proximity — instructions right
        next to the request scored 3 of 3, at the top of the block 1 of 3. Knowledge base and
        memory come first; the camera notice goes last, right against the request."""
        blocks: list[str] = []
        if kb:
            # Each piece arrives as "[file · page] text"; the model cites that label.
            blocks.append("[DOCUMENTOS DO USUÁRIO]\n" + "\n".join(f"• {c}" for c in kb)
                          + "\nAo usar estas informações, diga de qual documento vieram (como no rótulo). "
                            "Se a pergunta for sobre os documentos e nada aqui responder, diga que não encontrou nos "
                            "documentos guardados. Se a pergunta não for sobre eles, responda normalmente e não os cite."
                          + "\n[FIM DOS DOCUMENTOS]")
        profile = profile or []
        if profile:
            blocks.append("[SOBRE O USUÁRIO]\n" + "\n".join(f"• {f}" for f in profile) + "\n[FIM]")
        recall = [f for f in recall if f not in profile]
        if recall:
            blocks.append("[MEMÓRIA RELEVANTE]\n" + "\n".join(f"• {f}" for f in recall) + "\n[FIM DA MEMÓRIA]")
        camera = self._camera_hint()
        if camera:
            blocks.append(camera)
        return "\n\n".join(blocks + [user_text])

    def _trim_history(self) -> None:
        """Keeps the system prompt + the latest turns.

        Without this the panel conversation grew without bound and overflowed the model's
        4096 tokens — and whatever overflows is dropped from the START, taking the
        beginning of the conversation with it.

        The first item kept must be a 'user' one, otherwise a 'tool' message is left
        without the call that produced it and Ollama rejects it.
        """
        tail = self.history[1:][-CONFIG.ollama_history_turns * 2:]
        while tail and tail[0].get("role") != "user":
            tail.pop(0)
        # Long answers and tool results: whole turns go, oldest first, until the size fits.
        while sum(len(m.get("content") or "") for m in tail) > CONFIG.ollama_history_chars:
            next_turn = next((i for i, m in enumerate(tail) if i and m.get("role") == "user"), None)
            if next_turn is None:
                break
            tail = tail[next_turn:]
        self.history = self.history[:1] + tail

    async def _call_llm(self):
        return await asyncio.to_thread(
            self._client.chat,
            model=CONFIG.ollama_model,
            messages=self.history,
            tools=self._tool_schemas(),
            options=CONFIG.ollama_options,
            think=False,
            keep_alive=CONFIG.ollama_keep_alive,
        )

    async def _stream_llm(self) -> AsyncGenerator:
        """The reply as it is written, chunk by chunk, so the first sentence can be spoken while the
        rest is still being generated (before, the whole reply came first: measured 2026-11-04, the
        voice only started after the model finished). Read in a thread; closing the generator (the
        user interrupted) stops reading the stream. A client that returns one whole response (the
        tests' fakes) counts as a single chunk."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop = threading.Event()

        def read():
            try:
                response = self._client.chat(model=CONFIG.ollama_model, messages=self.history,
                                              tools=self._tool_schemas(), options=CONFIG.ollama_options,
                                              think=False, keep_alive=CONFIG.ollama_keep_alive, stream=True)
                for chunk in ([response] if hasattr(response, "message") else response):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))
            except Exception as e:          # noqa: BLE001 — raised again in the caller's task
                loop.call_soon_threadsafe(queue.put_nowait, ("error", e))

        threading.Thread(target=read, daemon=True, name="llm-stream").start()
        try:
            while True:
                kind, value = await queue.get()
                if kind == "chunk":
                    yield value
                elif kind == "end":
                    return
                else:
                    raise value
        finally:
            stop.set()

    async def chat_streaming(
        self,
        user_text: str,
        recall: list[str] | None = None,
        kb: list[str] | None = None,
        profile: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        self._refresh_date()
        entry = {"role": "user", "content": self._build_user_content(user_text, recall or [], kb or [], profile)}
        self.history.append(entry)
        try:
            async for sentence in self._answer():
                yield sentence
        finally:
            # Documents, profile and memories are for this turn only: left in the history, every
            # past turn carried ~1500 tokens of them and 8 turns overflowed the context.
            # The next turn looks them up again.
            entry["content"] = user_text

    async def _answer(self) -> AsyncGenerator[str, None]:
        rounds_done = 0
        retried_language = False
        self.used_tool = False         # replies that used a tool are not cached
        while True:
            rounds_done += 1
            if rounds_done > 8:
                # Safety net: a model stuck repeating tool calls would leave the UI
                # at "PROCESSANDO..." forever.
                yield "Me perdi entre as ferramentas. Pode reformular?"
                break
            visible = {s["function"]["name"] for s in self._tool_schemas()}
            content, calls, spoken = "", [], []
            held = False               # code or another script showed up: decide at the end, speak nothing more
            said_up_to = 0             # content[:said_up_to] was already yielded
            try:
                async for chunk in self._stream_llm():
                    message = chunk.message
                    calls += [(tc.function.name, tc.function.arguments) for tc in message.tool_calls or []]
                    content += message.content or ""
                    if held or calls:
                        continue
                    if _looks_like_code(content, visible):
                        held = True
                        continue
                    end = _complete_sentences_end(content, said_up_to)
                    for sentence in _split_sentences(content[said_up_to:end]):
                        if _foreign_script(sentence):
                            # Only from here on is decided at the end: the sentences already said
                            # before it must not come back in the tail.
                            held = True
                            said_up_to = content.find(sentence, said_up_to)
                            break
                        spoken.append(sentence)
                        yield sentence
                    if not held:
                        said_up_to = end
            except ollama.ResponseError as e:
                # The same derailment as the Thai replies, cut by Ollama: "token repeat limit reached".
                if "repeat" not in str(e) or retried_language or spoken:
                    raise
                log.warning(f"[Reply looped ({e}), retrying]")
                retried_language = True
                self.history.append({"role": "system", "content": "Responda somente em português do Brasil."})
                try:
                    msg = (await self._call_llm()).message
                finally:
                    self.history.pop()
                content = msg.content or ""
                calls = [(tc.function.name, tc.function.arguments) for tc in msg.tool_calls or []]
            reply = content.strip()
            if spoken and not calls:
                # Already speaking: the rest is said if it is still Portuguese, otherwise dropped.
                rest = content[said_up_to:]
                tail = [] if _foreign_script(rest) or _looks_like_code(rest, visible) else _split_sentences(rest)
                for sentence in tail:
                    yield sentence
                self.history.append({"role": "assistant", "content": " ".join(spoken + tail)})
                self._trim_history()
                break
            if not calls and _foreign_script(reply) and not retried_language:
                # Asked the same thing twice, the monitor's agent answered in Thai (app test,
                # 2026-11-02); with an overflowing context the main one answered in Chinese.
                # One more try with the order right next to the request; it is never spoken.
                log.warning(f"[Reply in another script, retrying: {said(repr(reply[:80]))}]")
                retried_language = True
                self.history.append({"role": "system", "content": "Responda somente em português do Brasil."})
                msg = (await self._call_llm()).message
                self.history.pop()
                reply = (msg.content or "").strip()
                calls = [(tc.function.name, tc.function.arguments) for tc in msg.tool_calls or []]
                if not calls and _foreign_script(reply):
                    reply = "Desculpe, me confundi. Pode repetir o pedido?"
            if not calls:
                calls = _calls_in_text(reply, visible)
                if calls:
                    log.info(f"[Call written as text: {said(repr(reply[:120]))}]")
                    reply = ""                 # it is code, not speech

            assistant_entry: dict = {"role": "assistant", "content": reply}
            if calls:
                assistant_entry["tool_calls"] = [
                    {"function": {"name": name, "arguments": args}} for name, args in calls
                ]
            self.history.append(assistant_entry)

            if not calls:
                for sentence in _split_sentences(reply):
                    yield sentence
                self._trim_history()
                break

            self.used_tool = True
            for name, args in calls:
                log.info(f"[Tool: {name}({said(args)})]")
                result = await asyncio.to_thread(self._dispatch or dispatch_tool, name, args)
                log.info(f"[Result: {said(result)}]")
                self.history.append({"role": "tool", "content": result})

    async def warmup(self):
        await asyncio.to_thread(
            self._client.chat,
            model=CONFIG.ollama_model,
            messages=[{"role": "user", "content": "oi"}],
            options=CONFIG.ollama_options,
            think=False,
            keep_alive=CONFIG.ollama_keep_alive,
        )

    async def unload(self) -> bool:
        return await asyncio.to_thread(unload_model, self._client)


def unload_model(client: ollama.Client | None = None) -> bool:
    """Takes the conversation model off the GPU (app asleep, or a game opened). Only when it is
    resident: a keep_alive=0 call on an unloaded model would load it first. True if it was."""
    client = client or ollama.Client(host=CONFIG.ollama_host, timeout=30)
    target = CONFIG.ollama_model if ":" in CONFIG.ollama_model else f"{CONFIG.ollama_model}:latest"
    if target not in {m.model for m in client.ps().models}:
        return False
    client.generate(model=CONFIG.ollama_model, keep_alive=0)
    return True
