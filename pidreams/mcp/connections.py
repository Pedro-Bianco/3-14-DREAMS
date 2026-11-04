"""One MCP client per running server, on its own asyncio loop.

Each server lives in a task that keeps the `mcp.Client` open until it is turned off; tool
calls come from other threads through `run_coroutine_threadsafe`. Failures become an
`erro(reason)` state and a notice with an action — the rest of the assistant carries on.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from pidreams.agent import problems
from pidreams.core import paths

log = logging.getLogger(__name__)

LIMIT_S = 60.0               # startup or call without an answer
CUTOFF = 4000                  # result characters that fit in the server turn
_LIFETIME_S = 5.0


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    read_only: bool          # no annotation = changes something


@dataclass
class _Server:
    name: str
    description: str                    # of the usar_<id> tool in the main conversation
    app_instructions: str               # what the app knows (e.g. allowed folders)
    only: set[str] | None               # subset of the tools offered (built-ins)
    no_confirm: set[str]           # treated as reads despite the annotation (built-ins)
    state: str = "desligado"         # desligado | iniciando | conectado | erro
    reason_text: str = ""
    tools: list[Tool] = field(default_factory=list)
    instructions: str = ""
    client: Client | None = None
    stop: asyncio.Event | None = None


def cut(text: str) -> str:
    if len(text) <= CUTOFF:
        return text
    return text[:CUTOFF] + f"\n[resultado cortado: {CUTOFF} de {len(text)} caracteres]"


class Connections:
    def __init__(self, on_notice: Callable[[dict], None] = lambda _p: None,
                 on_resolve: Callable[[str], None] = lambda _c: None,
                 on_change: Callable[[str], None] = lambda _id: None, limit_s: float = LIMIT_S):
        self._notify, self._resolve, self._changed = on_notice, on_resolve, on_change
        self.limit_s = limit_s
        self._servers: dict[str, _Server] = {}
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, name="mcp", daemon=True).start()

    # ── consulta ─────────────────────────────────────────────────────────────

    def state(self, id_: str) -> tuple[str, str]:
        s = self._servers.get(id_)
        return (s.state, s.reason_text) if s else ("desligado", "")

    def connected(self) -> list[str]:
        return [i for i, s in self._servers.items() if s.state == "conectado"]

    def name(self, id_: str) -> str:
        return self._servers[id_].name

    def description(self, id_: str) -> str:
        s = self._servers[id_]
        return s.description or (s.instructions[:300] if s.instructions else f"Usa a conexão {s.name}.")

    def tools(self, id_: str, all_items: bool = False) -> list[Tool]:
        s = self._servers.get(id_)
        if not s:
            return []
        return [f for f in s.tools if all_items or s.only is None or f.name in s.only]

    def instructions_for(self, id_: str) -> str:
        s = self._servers.get(id_)
        return "\n\n".join(t for t in (s.app_instructions, s.instructions) if t) if s else ""

    # ── ligar / desligar ─────────────────────────────────────────────────────

    def start_connection(self, id_: str, name: str, target: StdioServerParameters | str, description: str = "",
              instructions: str = "", only: set[str] | None = None,
              no_confirm: set[str] = frozenset()) -> None:
        """target: a local process (stdio) or a local address (http://127.0.0.1…)."""
        self.stop_connection(id_)
        server = _Server(name, description, instructions, only, set(no_confirm), state="iniciando")
        self._servers[id_] = server
        self._changed(id_)
        asyncio.run_coroutine_threadsafe(self._keep(id_, name, target, server), self._loop)

    def stop_connection(self, id_: str) -> None:
        server = self._servers.pop(id_, None)
        if server and server.stop:
            self._loop.call_soon_threadsafe(server.stop.set)
        self._resolve(f"mcp_{id_}")
        if server:
            self._changed(id_)

    def stop_all(self) -> None:
        for id_ in list(self._servers):
            self.stop_connection(id_)

    async def _keep(self, id_: str, name: str, target, server: _Server) -> None:
        server.stop = asyncio.Event()
        try:
            if isinstance(target, StdioServerParameters):
                paths.logs_dir().mkdir(parents=True, exist_ok=True)
                registry = open(paths.logs_dir() / f"mcp-{id_}.log", "a", encoding="utf-8")
                transport = stdio_client(target, errlog=registry)
            else:
                registry, transport = None, target
            try:
                async with Client(transport, read_timeout_seconds=self.limit_s) as client:
                    items = await asyncio.wait_for(client.list_tools(), self.limit_s)
                    server.tools = [Tool(
                        t.name, t.description or "", t.input_schema,
                        bool(t.annotations and t.annotations.read_only_hint) or t.name in server.no_confirm)
                        for t in items.tools]
                    server.instructions = client.instructions or ""
                    server.client, server.state = client, "conectado"
                    self._resolve(f"mcp_{id_}")
                    self._changed(id_)
                    log.info(f"[MCP] {name} connected: {len(server.tools)} tool(s)")
                    # Heartbeat every 5 s: the client does not notice on its own that the process
                    # died (measured), so a dead server becomes a notice within ~10 s.
                    # list_tools rather than ping: ping left the protocol on 2026-07-28 and newer
                    # servers answer "Method not found". Healthy: 1–2 ms.
                    while not server.stop.is_set():
                        try:
                            await asyncio.wait_for(server.stop.wait(), _LIFETIME_S)
                        except asyncio.TimeoutError:
                            await asyncio.wait_for(client.list_tools(), _LIFETIME_S)
            finally:
                if registry:
                    registry.close()
        except BaseException as e:       # includes anyio's exception group
            if server.stop.is_set():
                return                   # turned off on purpose
            self._failed(id_, name, server, _reason(e))
            return
        if not server.stop.is_set():  # o processo saiu sozinho
            self._failed(id_, name, server, "o servidor fechou")

    def _failed(self, id_: str, name: str, server: _Server, reason_text: str) -> None:
        log.warning(f"[MCP] {name}: {reason_text}")
        # The notice goes out BEFORE the state changes: whoever sees "erro" already finds it
        # (the other order made a test that waits for the state fail now and then).
        self._notify(problems.problem(
            f"mcp_{id_}", f"A conexão {name} parou: {reason_text}.",
            [("TENTAR DE NOVO", f"mcp_restart:{id_}"), ("VER LOG", f"mcp_log:{id_}")]))
        server.state, server.reason_text, server.client = "erro", reason_text, None
        self._changed(id_)

    # ── chamar ───────────────────────────────────────────────────────────────

    def call(self, id_: str, tool: str, arguments: dict) -> str:
        """Blocks the calling thread (never the MCP loop's). Errors come back as text for the
        model to answer the person, plus the panel notice when the server did not answer."""
        server = self._servers.get(id_)
        if not server or not server.client:
            return "Essa conexão não está ativa agora."
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(server.client.call_tool(tool, arguments), self.limit_s), self._loop)
        try:
            result = future.result()
        except (TimeoutError, asyncio.TimeoutError):
            future.cancel()
            self._notify(problems.problem(
                f"mcp_{id_}", f"A ferramenta {tool} não respondeu em {self.limit_s:.0f} s.",
                [("VER LOG", f"mcp_log:{id_}")], level="warning"))
            return f"A ferramenta {tool} não respondeu a tempo."
        except Exception as e:
            return f"Erro em {tool}: {_reason(e)}"
        text = "\n".join(getattr(b, "text", "") or f"[{type(b).__name__}]" for b in result.content)
        return cut(("Erro: " if result.is_error else "") + text)


def _reason(e: BaseException) -> str:
    """The useful message is at the bottom of anyio's exception group."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
        return "não respondeu a tempo"
    if isinstance(e, FileNotFoundError):
        return f"não encontrei {e.filename or 'o comando do servidor'}"
    return str(e) or type(e).__name__
