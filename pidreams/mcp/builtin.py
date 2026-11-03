"""Servers shipped with the app (off until the person turns them on) and how to start any server
from the preferences.

Built-in servers store in the preferences only whether they are on: command, version and
description live here, so an app update fixes all of them.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from mcp import StdioServerParameters

from pidreams.core import paths
from pidreams.mcp import runtime


@dataclass
class Builtin:
    name: str
    description: str            # of the usar_<id> tool, in Portuguese
    needs_node: bool


BUILTINS = {
    "arquivos": Builtin(
        "Arquivos",
        "Arquivos e pastas do computador que o usuário liberou: listar, procurar, ler, criar, "
        "mover e renomear. Use quando o pedido falar de arquivos, pastas, documentos ou downloads.",
        True),
    "navegador": Builtin(
        "Navegador",
        "Controla um navegador próprio: abre sites, lê a página, clica, digita e preenche "
        "formulários. Use quando o pedido for fazer algo dentro de um site.",
        True),
    "gmail": Builtin(
        "Gmail",
        "E-mails do usuário no Gmail: procurar, ler, resumir, criar rascunho, responder e enviar. "
        "Use quando o pedido falar de e-mail, caixa de entrada ou mensagens recebidas por e-mail.",
        False),
    "agenda": Builtin(
        "Agenda",
        "Agenda do Google do usuário (só leitura): compromissos de hoje, amanhã, da semana ou de "
        "um dia, e achar um compromisso pelo nome. Use quando o pedido falar de agenda, "
        "compromisso, reunião, consulta, horário marcado ou se o usuário está livre.",
        False),
}

# Tool name in the main conversation (agent/tools.mcp_tool_name).
BUILTIN_TOOL = {"arquivos": "files", "navegador": "browser", "gmail": "email", "agenda": "calendar"}

# Playwright marks even opening a site as "changes something": asking for "sim" on every page
# would make the browser useless. Opening, going back and switching tabs change nothing outside;
# clicking, typing, pressing keys, selecting and filling still ask (they may submit or buy).
BROWSER_NO_CONFIRM = {"browser_navigate", "browser_navigate_back", "browser_tabs"}

# The 10 essentials (1,524 tokens versus 3,952 for all 25); minus the ones that run code on the page.
BROWSER_ESSENTIALS = {
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type", "browser_press_key",
    "browser_navigate_back", "browser_wait_for", "browser_select_option", "browser_fill_form",
    "browser_tabs",
}


_MAX_TOP_LEVEL = 30


def _top_level(folder: str) -> str:
    """Top-level names, so the model knows the real paths (folders end with "/")."""
    try:
        items = sorted(Path(folder).iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return "?"
    names = [p.name + ("/" if p.is_dir() else "") for p in items[:_MAX_TOP_LEVEL]]
    rest = len(items) - len(names)
    return ", ".join(names) + (f" e mais {rest}" if rest > 0 else "") if names else "vazia"


def _app_arguments(server: str) -> list[str]:
    """PI dreams itself as an MCP server: the installed exe or `python -m pidreams`."""
    if getattr(sys, "frozen", False):
        return ["--mcp", server]
    return ["-m", "pidreams", "--mcp", server]


def needs_install(id_: str) -> bool:
    spec = BUILTINS.get(id_)
    return bool(spec and spec.needs_node and not runtime.is_ready())


def launch_params(id_: str, cfg: dict, folders: list[str]) -> dict:
    """Arguments for Connections.start_connection for server `id_` (built-in or the person's)."""
    cwd = paths.user_data_dir() / "mcp" / id_
    cwd.mkdir(parents=True, exist_ok=True)
    if id_ == "arquivos":
        if not folders:
            raise ValueError("Libere pelo menos uma pasta na aba Conexões.")
        node = str(runtime.node())
        target = StdioServerParameters(command=node, args=[str(runtime.module(
            "@modelcontextprotocol/server-filesystem")), *folders], cwd=cwd)
        # Measured: without knowing what is in the folders, the model guessed the Windows
        # Downloads folder; and search_files is a glob, so "*fatura de luz*" does not find
        # "fatura_luz_outubro.pdf" — only "**/*fatura*" does.
        instructions_for = ("Pastas liberadas (só estas existem para você): " + "; ".join(
            f"{p} (contém: {_top_level(p)})" for p in folders) + ". Use sempre caminhos "
            "completos que começam por uma pasta liberada. Para achar um arquivo, use "
            "search_files com pattern **/*palavra* usando UMA palavra-chave do nome, sem espaços "
            "nem acentos (ex.: **/*fatura*); se não achar, tente outra palavra. Antes de ler, "
            "mover ou renomear, descubra o caminho real com search_files ou list_directory e "
            "copie-o exatamente como veio no resultado. Se uma ferramenta der erro, corrija o "
            "caminho e tente de novo. Responda sempre em português do Brasil.")
        return {"name": BUILTINS[id_].name, "target": target, "description": BUILTINS[id_].description,
                "instructions": instructions_for}
    if id_ == "navegador":
        target = StdioServerParameters(command=str(runtime.node()), args=[
            str(runtime.module("@playwright/mcp")), "--browser", "msedge", "--isolated"], cwd=cwd)
        return {"name": BUILTINS[id_].name, "target": target, "description": BUILTINS[id_].description,
                "instructions": "Para ler uma página, use browser_snapshot depois de navegar.",
                "only": BROWSER_ESSENTIALS, "no_confirm": BROWSER_NO_CONFIRM}
    if id_ == "gmail":
        from pidreams.core import secrets

        account, password = cfg.get("conta", ""), secrets.get("mcp.gmail.senha_app") or ""
        if not account or not password:
            raise ValueError("Informe o endereço do Gmail e a senha de app na aba Conexões.")
        target = StdioServerParameters(command=sys.executable, args=_app_arguments("gmail"), cwd=cwd,
                                     env={"GMAIL_ACCOUNT": account, "GMAIL_APP_PASSWORD": password,
                                          "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
        return {"name": BUILTINS[id_].name, "target": target, "description": BUILTINS[id_].description,
                "instructions": f"Conta: {account}. Responda sempre em português do Brasil."}
    if id_ == "agenda":
        from pidreams.core import secrets

        url = secrets.get("mcp.agenda.url") or ""
        if not url:
            raise ValueError("Cole o endereço secreto da agenda (iCal) na aba Conexões.")
        target = StdioServerParameters(command=sys.executable, args=_app_arguments("agenda"), cwd=cwd,
                                     env={"CALENDAR_URL": url, "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
        return {"name": BUILTINS[id_].name, "target": target, "description": BUILTINS[id_].description,
                "instructions": "Responda sempre em português do Brasil."}
    if cfg.get("endereco"):
        target = cfg["endereco"]
    else:
        target = StdioServerParameters(command=cfg["comando"], args=list(cfg.get("argumentos", [])), cwd=cwd)
    return {"name": cfg.get("nome", id_), "target": target, "description": cfg.get("descricao", "")}
