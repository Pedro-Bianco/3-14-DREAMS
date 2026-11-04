"""Utilidades das avaliações contra o Ollama real.

Não rodam no pytest padrão: dependem do modelo instalado e da GPU. Rode, por
exemplo: python -m tests.eval.tools --model qwen2.5:14b
"""

import argparse
import sys
import time


def arguments(description: str) -> argparse.Namespace:
    sys.stdout.reconfigure(encoding="utf-8")       # console do Windows em cp1252 não imprime "→"
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--model", default=None, help="modelo do Ollama (padrão: o configurado)")
    p.add_argument("--persona", default=None, help="id da persona (quando existir)")
    p.add_argument("--rounds", type=int, default=1, help="repetições de cada caso")
    return p.parse_args()


def apply_model(model: str | None) -> str:
    from pidreams.core.config import CONFIG
    from pidreams.core.settings import SETTINGS

    if model:
        SETTINGS.set("llm.model", model)   # só em memória: não grava settings.json
    return CONFIG.ollama_model


def apply_persona(persona: str | None) -> None:
    if persona:
        from pidreams.core.settings import SETTINGS

        SETTINGS.set("persona_id", persona)


def report(title: str, results: list[tuple[str, bool]], start_at: float) -> int:
    hits = sum(ok for _, ok in results)
    for case, ok in results:
        print(f"{'OK   ' if ok else 'FALHA'} {case}")
    print(f"{title}: {hits}/{len(results)} em {time.time() - start_at:.0f}s")
    return hits
