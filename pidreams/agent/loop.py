import asyncio
import datetime
import logging
import queue as stdlib_queue
import threading
import time
from typing import Callable
from pidreams.audio.recorder import AudioRecorder
from pidreams.stt.transcriber import Transcriber
from pidreams.agent.llm import LLMAgent
from pidreams import pc, reminders
from pidreams.agent import problems, tools
from pidreams.mcp.confirmation import Confirmer
from pidreams.agent.memory_client import MemoryClient
from pidreams.audio.tts import VOICE_LEVEL, TTSEngine
from pidreams.core.config import CONFIG
from pidreams.core.settings import SETTINGS
from pidreams.memory.kb_store import label
from pidreams.monitor import agent as monitor_agent
from pidreams.research import agent as research_agent
from pidreams.memory.ltm_gate import has_personal_fact
from pidreams.memory.worker import mark_free, mark_busy
from pidreams.plugins.manager import memory_active


log = logging.getLogger(__name__)

# Only a whole utterance like these closes PI. Looking for the word anywhere closed the app on
# "eu quero desligar o PC em 5 minutos" (2026-11-01): "fechar", "desligar" and "parar" are PC
# actions since v0.3.0.
EXIT_PHRASES = {"sair", "encerrar", "encerra", "tchau", "tchau pi", "pode encerrar", "encerrar o pi"}


def is_exit_request(text: str) -> bool:
    return " ".join(text.lower().strip(" .,!?").split()) in EXIT_PHRASES


def _make_turns(user_text: str, reply: str) -> list[dict]:
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": reply},
    ]


class _Reflection:
    """Accumulates the conversation and hands a window to the memory extractor.

    Before, every question/answer pair was sent to the LTM on its own. Two isolated
    turns usually say nothing ("faça", "pode ser") and the extractor ran the LLM on
    every message, competing for the GPU with the reply to the user. Now it reflects
    every `ltm_reflect_every` turns, looking at the last `ltm_reflect_window`
    messages — which is where the context actually is.
    """

    def __init__(self, memory):
        self._memory = memory
        self._chat: list[dict] = []
        self._since_last = 0

    def register(self, user_text: str, reply: str) -> None:
        self._chat.extend(_make_turns(user_text, reply))
        self._since_last += 1
        # When the user has just stated something about themselves ("trabalho na Orbita",
        # "completei dois anos"), reflect NOW. Waiting for the window would leave the most
        # important fact of the conversation queued while trivia goes by.
        if has_personal_fact(user_text) or self._since_last >= CONFIG.ltm_reflect_every:
            self.reflect()

    def reflect(self) -> None:
        """Sends the window to the extractor. Also called when the session ends."""
        if self._since_last == 0 or len(self._chat) < 2:
            return
        window = self._chat[-CONFIG.ltm_reflect_window:]
        self._memory.submit_to_worker(window)
        self._since_last = 0


async def _log_latency(turn: dict[str, float], tts: TTSEngine) -> None:
    """One log line per voice turn: how long each stage took, from the end of the silence wait to
    the first sound. The silence wait itself is CONFIG.silence_duration_sec before 'heard'."""
    for _ in range(200):                       # the first sentence may still be synthesizing
        if tts.first_audio_at is not None:
            break
        await asyncio.sleep(0.05)
    audio = tts.first_audio_at
    stages = [("transcrição", turn["heard"], turn["stt"]), ("memória e Base", turn["stt"], turn["context"]),
              ("1ª frase do modelo", turn["context"], turn["first_sentence"])]
    if audio is not None:
        stages.append(("voz até tocar", turn["first_sentence"], audio))
    parts = " · ".join(f"{name} {end - start:.2f}s" for name, start, end in stages)
    total = (audio or turn["first_sentence"]) - turn["heard"]
    log.info(f"[Latency] silêncio {CONFIG.silence_duration_sec:.1f}s + {parts} = {total:.2f}s após o silêncio")


async def _deliver(emit: Callable, tts: TTSEngine, mode: str, chunks: list[str]):
    emit("agent_start")
    for chunk in chunks:
        emit("agent_chunk", chunk)
    emit("agent_end")
    if mode == "voice":
        for chunk in chunks:
            await tts.speak(chunk)
        await tts.drain()


async def _wait_text(text_input_queue: stdlib_queue.Queue, stop_event: asyncio.Event | None,
                     until: float = float("inf")) -> str | None:
    """None when stopping or at the `until` deadline (the loop goes back to check reminders)."""
    while True:
        try:
            return await asyncio.to_thread(text_input_queue.get, True, 0.3)
        except stdlib_queue.Empty:
            if (stop_event and stop_event.is_set()) or time.time() >= until:
                return None


_REMINDERS_INTERVAL_S = 30.0      # with the app open, notice within ~1 min of the time
_NOTHING_USED = {"profile": [], "memories": [], "pieces": []}   # replies that did not go through the model


def _briefing_text(connections, full_briefing: bool) -> str:
    """Briefing on open: the sources that are on and configured."""
    from pidreams import briefing

    now = datetime.datetime.now()
    notify = reminders.due_reminders(now, only_new=not full_briefing)
    reminders.mark_notified([l["id"] for l in notify])
    sources_map = briefing.sources(connections, now, SETTINGS.get("resumo") or {}, notify)
    return briefing.build(now, sources_map, full_briefing, SETTINGS.get("treatment").strip())


async def _vad_watch(
    recorder: AudioRecorder,
    interrupt_event: asyncio.Event,
    captured: list,
    stop_event: asyncio.Event | None,
    confirming: threading.Event,
):
    # During a confirmation the microphone belongs to it: the "sim" must not become an interruption.
    audio = await recorder.record_while_agent_speaks(
        interrupt_cb=interrupt_event.set,
        cancel_check=lambda: bool(stop_event and stop_event.is_set()) or confirming.is_set(),
        playback_level=lambda: VOICE_LEVEL[0],
    )
    captured.append(audio)


async def run_agent(
    on_event: Callable | None = None,
    stop_event: asyncio.Event | None = None,
    mode_ref: list[str] | None = None,
    text_input_queue: stdlib_queue.Queue | None = None,
    mic_device_ref: list | None = None,
    out_device_ref: list | None = None,
    volume_ref: list | None = None,
    mute_ref: list | None = None,
    ltm_store=None,
    kb_store=None,
    connections=None,
    monitor_ref: dict | None = None,
    research_ref: dict | None = None,
    sleep_ref: list | None = None,
):
    """monitor_ref: {"on": bool, "tools": MonitorAgentTools, "fresh": bool} — while "on", the
    monitor's own agent answers (no memory, documents or reflection in those turns).
    sleep_ref: [bool] — while True (app in the tray) the loop neither listens nor speaks and the
    conversation model is off the GPU; it is loaded again on waking, before listening."""
    def emit(etype: str, data=None):
        if on_event:
            on_event(etype, data)
        else:
            if etype == "status":        print(f"\n{data}")
            elif etype == "user":        print(f"\nVocê: {data}")
            elif etype == "agent_start": print("\nAgente: ", end="", flush=True)
            elif etype == "agent_chunk": print(data, end=" ", flush=True)
            elif etype == "agent_end":   print()

    def mode() -> str:
        return mode_ref[0] if mode_ref else "voice"

    def muted() -> bool:
        return bool(mute_ref[0]) if mute_ref else False

    def asleep() -> bool:
        return bool(sleep_ref[0]) if sleep_ref else False

    emit("status", "⏳ Carregando componentes...")

    recorder   = AudioRecorder(mic_device_ref=mic_device_ref)
    transcriber = Transcriber()
    llm        = LLMAgent()
    monitor_llm: LLMAgent | None = None     # created when the monitor opens, dropped when it reopens
    research_llm: LLMAgent | None = None    # same, for the deep-research mode

    def research_news() -> bool:
        """A research milestone or result is waiting to be spoken."""
        return research_ref is not None and not research_ref["tools"].announcements.empty()
    tts        = TTSEngine(out_device_ref=out_device_ref, volume_ref=volume_ref)
    tts.start()

    def _on_ltm_store(fact: str):
        emit("ltm_stored", fact)

    memory = await asyncio.to_thread(MemoryClient, ltm_store, _on_ltm_store)
    # A reply cached with the old persona/form of address would come back unchanged after the
    # switch (seen in the real app): any saved setting clears the cache.
    SETTINGS.subscribe(lambda _st: memory.cache_clear())
    kb_context = {"question": ""}       # last question that found document pieces
    reflection = _Reflection(memory)

    # Never gives up: notifies with an action and checks again until it is solved.
    while True:
        emit("status", "🔁 Verificando o Ollama...")
        if not await problems.wait_for_ollama(emit, stop_event):
            await tts.shutdown()
            return
        emit("status", "🔁 Verificando o modelo de conversa...")
        if not await problems.wait_for_model(emit, stop_event):
            await tts.shutdown()
            return
        if asleep():          # started in the tray: the model loads on waking
            break
        emit("status", "🔁 Carregando o modelo de conversa...")
        try:
            await llm.warmup()
            break
        except Exception as e:
            log.warning("warmup failed: %r", e)
            emit("problem", problems.from_chat(e))

    model_loaded = not asleep()
    await recorder.calibrate()

    # Confirmation for MCP tools that change something. Runs on the tool's thread;
    # speech and the microphone are requested from this loop.
    loop = asyncio.get_running_loop()
    confirming = threading.Event()
    listening: dict = {"vad": None}

    async def _speak(text: str):
        await tts.speak(text)
        await tts.drain()

    def _ask(briefing: str):
        confirming.set()
        emit("problem", problems.problem(
            "confirm", f"Posso fazer isto? {briefing}",
            [("CONFIRMAR", "confirm_yes"), ("CANCELAR", "confirm_no")], level="warning"))
        if mode() == "voice":
            asyncio.run_coroutine_threadsafe(
                _speak(f"Posso fazer isto: {briefing}? Diga sim para confirmar."), loop).result()

    def _listen(cancel: threading.Event, deadline: float) -> str | None:
        end = time.time() + deadline
        if mode() == "voice" and not muted():
            vad = listening["vad"]
            if vad is not None and not vad.done():          # espera ele soltar o microfone
                asyncio.run_coroutine_threadsafe(asyncio.wait([vad], timeout=2), loop).result()
            recording = asyncio.run_coroutine_threadsafe(recorder.record_until_silence(
                cancel_check=lambda: cancel.is_set() or time.time() > end), loop)
            try:
                audio = recording.result(timeout=deadline + 1)
            except Exception:
                return None
            return None if cancel.is_set() else transcriber.transcribe(audio)
        while not cancel.is_set() and time.time() < end and text_input_queue is not None:
            try:
                return text_input_queue.get(timeout=0.3)
            except stdlib_queue.Empty:
                pass
        return None

    def _shutdown():
        confirming.clear()
        emit("resolved", "confirm")

    tools.configure_mcp(connections, Confirmer(_ask, _listen, _shutdown))

    async def _briefing():
        # Briefing instead of "Estou pronto": full once a day (or every time the app opens, if the
        # user chose so), otherwise reminders only.
        emit("status", "🟢 Pronto — fale algo")
        today = datetime.date.today()
        briefing_settings = SETTINGS.get("resumo") or {}
        full_briefing = briefing_settings.get("ligado", True) and (
            briefing_settings.get("toda_vez", False) or reminders.last_briefing() != today.isoformat())
        if full_briefing:
            await asyncio.sleep(2)                 # gives saved connections time to reconnect
        initial_text = await asyncio.to_thread(_briefing_text, connections, full_briefing)
        if full_briefing:
            reminders.record_briefing(today)
        # Muted or text mode: the briefing only shows in the chat.
        await _deliver(emit, tts, "text" if muted() else mode(), [initial_text])
        await tts.drain()

    briefing_due = True             # given on the first moment awake (a tray start waits for the wake)
    next_check = time.time() + _REMINDERS_INTERVAL_S
    next_unload = 0.0

    pending_text: str | None = None

    while True:
        if stop_event and stop_event.is_set():
            break

        if asleep():
            # Background memory jobs may load the model again: checked every 30 s while asleep.
            if model_loaded or time.time() >= next_unload:
                emit("status", "💤 Dormindo na bandeja")
                try:
                    await llm.unload()
                except Exception as e:
                    log.warning("unload on sleep failed: %r", e)
                model_loaded, next_unload = False, time.time() + 30
            await asyncio.sleep(0.2)
            continue
        if not model_loaded:
            emit("status", "🔁 Carregando o modelo de conversa...")
            try:
                started = time.perf_counter()
                await llm.warmup()
                log.info("wake: model loaded in %.1f s", time.perf_counter() - started)
                model_loaded = True
            except Exception as e:
                log.warning("warmup on wake failed: %r", e)
                emit("problem", problems.from_chat(e))
                await asyncio.sleep(3)
                continue
            if not briefing_due:
                emit("status", "🟢 Pronto — fale algo")
        if briefing_due:
            briefing_due = False
            await _briefing()

        if time.time() >= next_check:
            # Reminder due with the app open: announce it between replies.
            next_check = time.time() + _REMINDERS_INTERVAL_S
            new_items = reminders.due_reminders(datetime.datetime.now(), only_new=True)
            if new_items:
                reminders.mark_notified([l["id"] for l in new_items])
                from pidreams.briefing import reminders_phrase

                await _deliver(emit, tts, "text" if muted() else mode(),
                               [reminders_phrase(new_items, datetime.datetime.now())])
                await tts.drain()

        # Deep research runs in the background; its milestones and summary are spoken between turns.
        while research_news():
            note = research_ref["tools"].announcements.get_nowait()
            await _deliver(emit, tts, "text" if muted() else mode(), [note])
            await tts.drain()

        if pending_text is None and text_input_queue is not None and mode() == "voice":
            try:
                pending_text = text_input_queue.get_nowait()     # ex.: "tentar de novo"
            except stdlib_queue.Empty:
                pass

        turn: dict[str, float] = {}       # timestamps of this voice turn, for the latency log
        if pending_text:
            text = pending_text
            pending_text = None
        elif mode() == "voice":
            if muted():
                emit("status", "🔇 Microfone mudo")
                await asyncio.sleep(0.15)
                continue
            emit("status", "🎤 Aguardando fala...")
            try:
                audio = await recorder.record_until_silence(
                    cancel_check=lambda: (mode() != "voice" or muted() or bool(stop_event and stop_event.is_set())
                                          or research_news() or asleep())
                )
            except Exception as e:
                log.warning("microphone: %r", e)
                emit("problem", problems.from_microphone(e))
                if mic_device_ref is not None:
                    mic_device_ref[0] = None          # back to the Windows default
                await asyncio.sleep(3)
                continue
            if stop_event and stop_event.is_set():
                break
            if mode() != "voice" or muted() or asleep():
                continue
            turn["heard"] = time.perf_counter()            # end of speech + the silence wait
            text = transcriber.transcribe(audio)
            turn["stt"] = time.perf_counter()
            if not text:
                continue
        else:
            emit("status", "⌨️ Aguardando mensagem...")
            # Back every second: research milestones and going to sleep are noticed quickly.
            text = await _wait_text(text_input_queue, stop_event, until=min(next_check, time.time() + 1))
            if text is None:
                continue

        emit("user", text)

        if is_exit_request(text):
            farewell = "Encerrando o agente. Até logo!"
            await _deliver(emit, tts, mode(), [farewell])
            break

        # A pending shutdown is cancelled by code, never left to the model's tool choice.
        if pc.pending_shutdown() and pc.is_cancel_request(text):
            emit("context_used", _NOTHING_USED)
            await _deliver(emit, tts, mode(), [await asyncio.to_thread(pc.cancelar_desligamento)])
            continue

        monitoring = bool(monitor_ref and monitor_ref.get("on"))
        researching = bool(research_ref and research_ref.get("on"))
        # Deep research: cancel, open and close are decided by code, like the monitor.
        if research_ref is not None:
            command = None
            if research_ref["tools"].running and research_agent.is_cancel_request(text):
                research_ref["tools"].cancel()
                command = (None, "Cancelando a pesquisa.")
            elif research_ref["tools"].awaiting:
                # Answer to the clarifying questions ("a segunda", "tanto faz"), not a new request.
                command = (None, research_ref["tools"].answer_text(text))
            elif not researching and research_agent.is_open_request(text):
                command = ("research_open", "Abrindo a Pesquisa profunda.")
            elif researching and research_agent.is_close_request(text):
                command = ("research_close", "Pesquisa profunda fechada.")
            if command:
                emit("context_used", _NOTHING_USED)
                if command[0]:
                    emit(command[0])
                await _deliver(emit, tts, mode(), [command[1]])
                continue
        if monitor_ref is not None and not monitoring and monitor_agent.is_open_request(text):
            emit("context_used", _NOTHING_USED)
            emit("monitor_open")
            await _deliver(emit, tts, mode(), ["Abrindo o Monitoramento."])
            continue
        # Closing the monitor is decided by code, like cancelling a shutdown.
        if monitoring and monitor_agent.is_close_request(text):
            emit("context_used", _NOTHING_USED)
            emit("monitor_close")
            await _deliver(emit, tts, mode(), ["Monitoramento fechado."])
            continue
        if monitoring and (tool := monitor_agent.direct_command(text)):
            emit("context_used", _NOTHING_USED)
            await _deliver(emit, tts, mode(), [monitor_ref["tools"].dispatch(tool, {})])
            continue
        if monitoring:
            text = monitor_agent.name_selected_plane(text, monitor_ref["tools"].selected_flight())

        emit("status", "🤔 Processando...")
        mark_busy()      # holds the LTM reflection while the user waits

        use_memory = memory.available and memory_active() and not monitoring and not researching

        if use_memory:
            cached = await asyncio.to_thread(memory.cache_get, text)
            if cached:
                emit("context_used", _NOTHING_USED)
                await _deliver(emit, tts, mode(), [cached])
                reflection.register(text, cached)
                continue

        # Memory is looked up on every question by similarity (above ltm_score_min), plus the short
        # profile always: with trigger words only ("meu", "lembra"), a saved preference
        # never reached an ordinary request.
        query_vector = await asyncio.to_thread(memory.embed_query, text) if use_memory else None
        recall_task = asyncio.create_task(memory.search(text, query_vector)) if use_memory else None
        profile = await asyncio.to_thread(memory.profile) if use_memory else []

        # With documents saved, every question looks them up (not only trigger words): the search
        # only returns pieces above the score floor, so unrelated questions get nothing. A follow-up
        # ("e o prazo?") carries the previous question when that one found pieces.
        use_kb = (memory_active() and not monitoring and not researching and kb_store is not None and kb_store.available
                  and kb_store.count() > 0)
        kb_query = f"{kb_context['question']} {text}" if kb_context["question"] else text
        kb_task = asyncio.create_task(asyncio.to_thread(
            kb_store.search_hits, kb_query, query_vector if kb_query == text else None)) if use_kb else None

        interrupt_event = asyncio.Event()
        captured: list = []

        vad_task = asyncio.create_task(
            _vad_watch(recorder, interrupt_event, captured, stop_event, confirming)
        ) if mode() == "voice" and not muted() else None
        listening["vad"] = vad_task

        recall = await recall_task if recall_task else []
        if recall:
            emit("status", f"🧠 {len(recall)} memória(s) recuperada(s)")

        kb_hits = await kb_task if kb_task else []
        kb_recall = [f"[{label(h)}] {h['text']}" for h in kb_hits]
        kb_context["question"] = text if kb_recall else ""
        if kb_recall:
            emit("status", f"📚 {len(kb_recall)} trecho(s) da base de conhecimento")
        # What goes to the model this turn, for the memory graph to highlight.
        emit("context_used", {"profile": profile, "memories": [m for m in recall if m not in profile],
                              "pieces": [[h["source"], h.get("where", "")] for h in kb_hits]})

        agent = llm
        if monitoring:
            if monitor_llm is None or monitor_ref.pop("fresh", False):
                monitor_tools = monitor_ref["tools"]
                monitor_llm = LLMAgent(system_prompt=monitor_agent.prompt(), tools=monitor_tools.schemas,
                                       dispatch=monitor_tools.dispatch)
            agent = monitor_llm
        elif researching:
            if research_llm is None or research_ref.pop("fresh", False):
                research_tools = research_ref["tools"]
                research_llm = LLMAgent(system_prompt=research_agent.prompt(), tools=research_tools.schemas,
                                        dispatch=research_tools.dispatch)
            agent = research_llm

        reply_parts: list[str] = []
        history_before = len(agent.history)
        if turn:
            turn["context"] = time.perf_counter()
        tts.first_audio_at = None
        try:
            emit("agent_start")
            async for sentence in agent.chat_streaming(text, recall=recall, kb=kb_recall, profile=profile):
                if interrupt_event.is_set() or asleep():      # sent to the tray mid-reply: hush
                    break
                if not reply_parts and turn:
                    turn["first_sentence"] = time.perf_counter()
                emit("agent_chunk", sentence)
                reply_parts.append(sentence)
                if mode() == "voice":
                    await tts.speak(sentence)
            emit("agent_end")
            log.info("[Reply] %d sentence(s): %s", len(reply_parts), " | ".join(reply_parts)[:600])
            if turn.get("first_sentence"):
                asyncio.create_task(_log_latency(turn, tts))
        except Exception as e:
            emit("agent_end")
            log.warning("reply failed: %r", e)
            del agent.history[history_before:]      # "tentar de novo" does not duplicate the question
            emit("problem", problems.from_chat(e) | {"retry_text": text})
            if mode() == "voice":
                await tts.speak("Não consegui responder agora.")

        if vad_task is not None:
            if interrupt_event.is_set():
                tts.interrupt()
                emit("status", "⚡ Interrompido — aguardando fala...")
                try:
                    await asyncio.wait_for(asyncio.shield(vad_task), timeout=10.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    vad_task.cancel()
            else:
                vad_task.cancel()
                try:
                    await vad_task
                except asyncio.CancelledError:
                    pass

        if asleep():
            tts.interrupt()
        elif mode() == "voice" and not interrupt_event.is_set():
            emit("status", "🔊 Respondendo...")
            await tts.drain()

        if not interrupt_event.is_set() and reply_parts and use_memory:
            full_reply = " ".join(reply_parts)
            # Calendar, e-mail and search change: the same question later must go to the source.
            if not llm.used_tool:
                await asyncio.to_thread(memory.cache_put, text, full_reply)
            reflection.register(text, full_reply)

        mark_free()

        if mode() == "voice" and captured and len(captured[0]) > 0:
            new_text = transcriber.transcribe(captured[0])
            if new_text:
                pending_text = new_text

    reflection.reflect()      # keeps what was left in the buffer when shutting down
    emit("status", "Guardando memórias…")
    mark_free()               # closed mid-reply: the worker would wait for a reply that never comes
    await asyncio.to_thread(memory.drain, CONFIG.ltm_exit_wait_s)
    await tts.shutdown()
