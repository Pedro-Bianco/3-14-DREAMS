"""Servidor MCP de teste: uma ferramenta de cada tipo que o cliente precisa tratar.

Roda por stdio (`python tests/fixtures/test_server.py`) ou em memória (`SERVIDOR`). Só dados
fictícios, guardados em memória.
"""

import asyncio
import sys

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

SERVER = MCPServer("teste", instructions="Guarda e lê notas curtas.")
_NOTES = {"compras": "pão, leite e café"}


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
def read_note(title: str) -> str:
    """Lê uma nota pelo título."""
    return _NOTES.get(title, "nota não encontrada")


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
def write_note(title: str, text: str) -> str:
    """Grava (ou substitui) uma nota."""
    _NOTES[title] = text
    return f"nota '{title}' gravada"


@SERVER.tool()
def unannotated(title: str) -> str:
    """Apaga uma nota (sem dizer se altera algo: o cliente deve tratar como alteração)."""
    _NOTES.pop(title, None)
    return f"nota '{title}' apagada"


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
async def slow(seconds: float) -> str:
    """Demora o tempo pedido para responder."""
    await asyncio.sleep(seconds)
    return "terminou"


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
def large() -> str:
    """Devolve um texto enorme."""
    return "linha fictícia de teste. " * 2000


if __name__ == "__main__":
    if "--quebrar" in sys.argv:
        sys.exit(3)                      # simula servidor que não inicia
    SERVER.run("stdio")
