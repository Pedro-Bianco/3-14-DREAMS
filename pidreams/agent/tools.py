import os
import subprocess
import webbrowser
import urllib.request
import urllib.parse
import re
import html as _html_mod
import pyperclip
from html.parser import HTMLParser
from typing import Any

from pidreams import pc, reminders


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# 6000 characters ~= 1700 tokens: on its own it ate 40% of the 4096 window and
# pushed the start of the conversation out.
_SCRAPE_CHAR_LIMIT = 3500
_SCRAPE_JS_THRESHOLD = 300

_allowed_apps: set | None = None


def set_allowed_apps(apps: set | None) -> None:
    global _allowed_apps
    _allowed_apps = apps


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "head", "nav", "footer", "header",
             "aside", "form", "button", "noscript", "iframe"}
    _BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div",
              "br", "tr", "article", "section", "main", "blockquote"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1
        if tag in self._BLOCK and self._depth == 0:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth > 0:
            self._depth -= 1
        if tag in self._BLOCK and self._depth == 0:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def result(self) -> str:
        text = " ".join(self._parts)
        lines = [ln.strip() for ln in text.split("\n")]
        return "\n".join(ln for ln in lines if ln)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": (
                "Abre um aplicativo ou arquivo no computador do usuário. "
                "Use apenas quando o usuário pedir explicitamente para abrir algo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "Nome do executável (ex: 'notepad', 'calc', 'chrome') "
                            "ou caminho completo do arquivo a abrir."
                        ),
                    }
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Pesquisa na internet e retorna os resultados com trechos das páginas encontradas. "
                "Use quando o usuário pedir para pesquisar, ou quando a pergunta envolver fatos "
                "atuais, notícias, preços, eventos ou qualquer informação disponível na web."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Termo ou pergunta a pesquisar.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_read",
            "description": "Lê o conteúdo atual da área de transferência (Ctrl+C).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_write",
            "description": "Copia um texto para a área de transferência.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Texto a ser copiado.",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_url",
            "description": (
                "Acessa uma URL e extrai o conteúdo textual da página web. "
                "Use SEMPRE que o usuário enviar ou mencionar um link ou URL "
                "(começando com http:// ou https://) para que você possa ler e "
                "responder sobre o conteúdo da página."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "A URL completa da página a ser acessada (ex: https://exemplo.com/artigo).",
                    }
                },
                "required": ["url"],
            },
        },
    },
    *reminders.SCHEMAS,        # criar, ver e tirar lembretes
    *pc.SCHEMAS,               # volume, música, janelas, brilho, desligar
]


def _fetch(url: str, *, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].strip().split(";")[0].strip()
        return resp.read().decode(charset, errors="ignore")


def open_app(target: str) -> str:
    if _allowed_apps is not None:
        basename = os.path.basename(target).lower().replace(".exe", "").strip()
        if basename not in _allowed_apps:
            return f"Acesso negado: '{basename}' não está na lista de apps permitidos."
    try:
        os.startfile(target)
        return f"Abrindo: {target}"
    except Exception:
        try:
            subprocess.Popen(f"start {target}", shell=True)
            return f"Comando enviado para abrir: {target}"
        except Exception as e:
            return f"Erro ao abrir '{target}': {e}"


def web_search(query: str) -> str:
    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")
    try:
        body = _fetch(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}")
        titles   = re.findall(r'class="result__a"[^>]*>(.*?)</a>',       body, re.DOTALL | re.IGNORECASE)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL | re.IGNORECASE)

        def clean(html: str) -> str:
            return _html_mod.unescape(re.sub(r"<[^>]+>", "", html).strip())

        parts = [
            f"• {clean(t)}\n  {clean(s)}"
            for t, s in zip(titles[:5], snippets[:5])
            if t or s
        ]
        if parts:
            return f"Resultados para '{query}':\n\n" + "\n\n".join(parts)
    except Exception:
        pass
    return f"Busca aberta no navegador para: {query}"


def _scrape_static(url: str) -> str:
    parser = _TextExtractor()
    parser.feed(_fetch(url, timeout=15))
    return parser.result()


def scrape_url(url: str) -> str:
    try:
        text = _scrape_static(url)
    except Exception as e:
        return f"Erro ao acessar '{url}': {e}"

    # No embedded browser (Playwright was dropped from the product: ~150 MB more in the
    # installer): a page that only builds its content with JavaScript yields no text.
    if len(text.strip()) < _SCRAPE_JS_THRESHOLD:
        return (f"A página {url} quase não tem texto sem JavaScript, e eu só leio o HTML "
                "estático. Diga isso ao usuário e sugira colar o conteúdo aqui.")

    if len(text) > _SCRAPE_CHAR_LIMIT:
        text = text[:_SCRAPE_CHAR_LIMIT] + "\n...[conteúdo truncado]"

    return f"[Conteúdo de {url}]\n\n{text}"


def clipboard_read() -> str:
    content = pyperclip.paste()
    return content if content else "(área de transferência vazia)"


def clipboard_write(text: str) -> str:
    pyperclip.copy(text)
    preview = text[:60] + "..." if len(text) > 60 else text
    return f"Copiado para a área de transferência: {preview}"


TOOL_REGISTRY: dict[str, Any] = {
    "open_app":        open_app,
    "web_search":      web_search,
    "clipboard_read":  clipboard_read,
    "clipboard_write": clipboard_write,
    **reminders.FUNCTIONS,
    **pc.FUNCTIONS,
    "scrape_url":      scrape_url,
}


# ── Services the GUI can turn on and off ──────────────────────────────────────
# A service's tools only go into the schema sent to the LLM while the service is
# on. Turning it off really removes the capability — the model does not even see
# the tool — and dispatch refuses it as a safeguard.

SERVICE_TOOLS: dict[str, set[str]] = {}
_enabled_services: set[str] = set()


def register_service_tools(service: str, schemas: list[dict], handlers: dict) -> None:
    """Registers tools that belong to a service. Idempotent."""
    SERVICE_TOOLS.setdefault(service, set()).update(
        s["function"]["name"] for s in schemas
    )
    already_has = {s["function"]["name"] for s in TOOL_SCHEMAS}
    TOOL_SCHEMAS.extend(s for s in schemas if s["function"]["name"] not in already_has)
    TOOL_REGISTRY.update(handlers)


def set_service_enabled(service: str, enabled: bool) -> None:
    if enabled:
        _enabled_services.add(service)
    else:
        _enabled_services.discard(service)


def is_service_enabled(service: str) -> bool:
    return service in _enabled_services


def _gated_names() -> set[str]:
    return {
        name
        for service, names in SERVICE_TOOLS.items()
        if service not in _enabled_services
        for name in names
    }


def active_tool_schemas() -> list[dict]:
    """Schemas visible right now: without the services that are off, plus one tool per
    connected MCP server (its own tools do not fit here)."""
    gated = _gated_names()
    out = [s for s in TOOL_SCHEMAS if s["function"]["name"] not in gated]
    connections = _MCP["connections"]
    for name, id_ in _mcp_tools().items():
        out.append(_use_schema(name, connections.description(id_)))
    return out


def mcp_tool_name(id_: str) -> str:
    """Name of the server's tool in the main conversation. Built-in servers use short English
    names: with "usar_arquivos" qwen2.5:14b wrote the call as text and sometimes without the
    name ("_icall_files {...}"); with "files" it got it right more often."""
    from pidreams.mcp.builtin import BUILTIN_TOOL

    return BUILTIN_TOOL.get(id_, f"usar_{id_}")


def _mcp_tools() -> dict[str, str]:
    connections = _MCP["connections"]
    return {mcp_tool_name(i): i for i in connections.connected()} if connections else {}


# MCP connections and the function that asks the person for a "sim"; set up by the agent loop.
_MCP: dict = {"connections": None, "confirm": lambda _briefing: False}


def configure_mcp(connections, confirm) -> None:
    _MCP.update(connections=connections, confirm=confirm)
    pc.configure(confirm)             # same "sim" for the sensitive PC actions


def _use_schema(name: str, description: str) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {"pedido": {
            "type": "string",
            "description": "O que fazer, com todos os detalhes do usuário (nomes, pastas, sites)."}},
            "required": ["pedido"]}}}


def _use_server(id_: str, request: str) -> str:
    from pidreams.mcp import server_turn

    connections = _MCP["connections"]
    if not connections or id_ not in connections.connected():
        return f"[Erro] A conexão '{id_}' não está ligada no painel do PI dreams."
    if not request.strip():
        return (f"[Erro] A chamada de '{mcp_tool_name(id_)}' veio sem pedido. "
                "Chame de novo preenchendo o pedido.")
    try:
        return server_turn.execute(connections, id_, connections.name(id_), request, connections.instructions_for(id_),
                              connections.tools(id_), _MCP["confirm"])
    except Exception as e:      # a failed turn becomes a result; it does not break the whole reply
        return f"[Erro] A conexão {connections.name(id_)} falhou: {e}"


def dispatch_tool(name: str, arguments: dict) -> str:
    mcp = _mcp_tools()
    if name in mcp or name.startswith("usar_"):
        return _use_server(mcp.get(name, name[len("usar_"):]), str(arguments.get("pedido", "")))
    for service, names in SERVICE_TOOLS.items():
        if name in names and service not in _enabled_services:
            return f"[Erro] O serviço '{service}' está desligado no painel do PI dreams."
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return f"[Erro] Ferramenta desconhecida: {name}"

    # Local models sometimes emit the call without arguments. A raw Python TypeError
    # does not tell the model what to do; a direct instruction lets it fix itself on
    # the next turn instead of giving up and asking the user.
    missing_items = _missing_arguments(name, arguments)
    if missing_items:
        return (
            f"[Erro] A chamada de '{name}' veio sem {', '.join(missing_items)}. "
            f"Chame de novo preenchendo: {', '.join(missing_items)}. "
            "Os valores já estão na conversa — não peça ao usuário de novo."
        )

    try:
        return fn(**arguments)
    except TypeError as e:
        return (
            f"[Erro] Argumentos inválidos para '{name}': {e}. "
            "Confira os nomes dos parâmetros no schema e chame de novo."
        )
    except Exception as e:
        return f"[Erro ao executar '{name}']: {e}"


def _missing_arguments(name: str, arguments: dict) -> list[str]:
    for schema in TOOL_SCHEMAS:
        if schema["function"]["name"] != name:
            continue
        required = schema["function"]["parameters"].get("required", [])
        return [a for a in required if not str(arguments.get(a, "")).strip()]
    return []
