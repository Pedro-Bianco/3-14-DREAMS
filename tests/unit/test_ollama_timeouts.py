"""Todo cliente do Ollama tem tempo limite.

Sem limite, um servidor que aceita a conexão e nunca responde deixava o app em
"carregando" para sempre — aconteceu em 2026-10-16.
"""

import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CALL = re.compile(r"ollama\.Client\(([^)]*)\)")


def test_nenhum_cliente_sem_timeout():
    unbounded = []
    for path in (ROOT_DIR / "pidreams").rglob("*.py"):
        for m in CALL.finditer(path.read_text(encoding="utf-8")):
            if "timeout" not in m.group(1):
                unbounded.append(f"{path.relative_to(ROOT_DIR)}: {m.group(0)}")
    assert not unbounded, unbounded
