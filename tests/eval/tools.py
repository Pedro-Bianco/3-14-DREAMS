"""Avaliação de ferramentas: turno completo do agente, por categoria.

As ferramentas são falsas (registram a chamada e devolvem um resultado plausível): nada é
aberto, pesquisado ou copiado de verdade. Confere ferramentas chamadas, argumentos e se a
resposta afirma uma ação que não aconteceu.

Uso: python -m tests.eval.tools --model qwen2.5:14b [--rounds 2] [--category camera_deve] [--validation]
"""

import asyncio
import re
import statistics
import time
from collections import defaultdict

from tests.eval._common import apply_model, apply_persona, arguments
from tests.eval.tool_cases import CASES, VALIDATION, Case

_FAKE_RESULTS = {
    "open_app": lambda a: f"Abrindo: {a.get('target', '')}",
    "web_search": lambda a: (f"Resultados para '{a.get('query', '')}':\n\n• Página de exemplo\n"
                             "  Informação fictícia encontrada agora sobre o assunto."),
    "scrape_url": lambda a: (f"[Conteúdo de {a.get('url', '')}]\n\nTítulo: Exemplo fictício\n"
                             "Texto de exemplo com algumas frases sobre o assunto da página."),
    "clipboard_read": lambda a: "Reunião de equipe amanhã às 10h na sala 3.",
    "clipboard_write": lambda a: f"Copiado para a área de transferência: {a.get('text', '')[:60]}",
    "ver_camera": lambda a: "A imagem mostra uma pessoa de camiseta azul segurando uma caneca branca.",
}

# Afirmações de ação concluída: com a ferramenta não chamada, são mentira.
_CLAIMS_ACTION = re.compile(
    r"\b(abri|abrindo|aberto|aberta|pesquisei|procurei|busquei|pesquisando|copiei|copiado|copiada|"
    r"li a página|li o (conteúdo|artigo|link)|lendo a página|vi que você|estou te vendo|"
    r"vejo que você|você está (usando|segurando|vestindo))\b", re.IGNORECASE)


async def _turn(case: Case) -> tuple[list[tuple[str, dict]], str, float]:
    from pidreams.agent import llm as llm_module
    from pidreams.agent.tools import set_service_enabled

    calls: list[tuple[str, dict]] = []

    def fake(name, arguments):
        calls.append((name, dict(arguments)))
        return _FAKE_RESULTS.get(name, lambda a: "ok")(arguments)

    llm_module.dispatch_tool = fake
    set_service_enabled("camera", case.camera)
    agent = llm_module.LLMAgent()
    agent.history += [{"role": role, "content": text} for role, text in case.before]
    start_at = time.perf_counter()
    phrases = [f async for f in agent.chat_streaming(case.phrase)]
    return calls, " ".join(phrases), time.perf_counter() - start_at


def _check(case: Case, calls, reply) -> list[str]:
    """Lista de problemas; vazia = acerto."""
    names = {n for n, _ in calls}
    accepted = [case.expected] + ([case.also] if case.also is not None else [])
    problems = []
    if names not in accepted:
        problems.append(f"chamou {sorted(names) or 'nada'}, esperado {sorted(case.expected) or 'nada'}")
    for name, (field, snippets) in case.args.items():
        values = [str(a.get(field, "")).lower() for n, a in calls if n == name]
        if values and not any(t.lower() in v for v in values for t in snippets):
            problems.append(f"argumento {name}.{field}={values[0]!r} sem {snippets}")
    if case.expected - names and _CLAIMS_ACTION.search(reply):
        problems.append(f"AFIRMOU SEM FAZER: {reply[:90]!r}")
    return problems


def main():
    import argparse
    import sys

    extra = argparse.ArgumentParser(add_help=False)
    extra.add_argument("--category", default=None)
    extra.add_argument("--validation", action="store_true", help="usa o conjunto de validação")
    extra.add_argument("--mcp", action="store_true",
                       help="com o servidor de arquivos ligado (a ferramenta 'files' visível)")
    options, rest = extra.parse_known_args()
    sys.argv = [sys.argv[0]] + rest
    args = arguments(__doc__)
    model = apply_model(args.model)
    apply_persona(args.persona)
    from pidreams.core.settings import SETTINGS

    # Tratamento fixo e fictício: resultado reproduzível e sem dados da pessoa.
    SETTINGS.set("treatment", "chefe")             # só em memória: não grava settings.json
    from pidreams.camera import tools as camera_tools

    camera_tools.register()
    if options.mcp:
        from types import SimpleNamespace

        from pidreams.agent import tools
        from pidreams.mcp.builtin import BUILTINS

        # Só a presença da ferramenta muda a escolha do modelo; chamá-la conta como erro em
        # qualquer caso desta avaliação (nenhum pede arquivos).
        tools.configure_mcp(SimpleNamespace(connected=lambda: ["arquivos"],
                                             description=lambda _i: BUILTINS["arquivos"].description),
                             lambda _r: False)
    cases = [c for c in (VALIDATION if options.validation else CASES) if not options.category or c.category == options.category]

    hits, totals, failures, lies = defaultdict(int), defaultdict(int), [], 0
    times_no_tool = []
    start_at = time.time()
    for _ in range(args.rounds):
        for case in cases:
            calls, reply, dt = asyncio.run(_turn(case))
            problems = _check(case, calls, reply)
            totals[case.category] += 1
            hits[case.category] += not problems
            lies += any(p.startswith("AFIRMOU") for p in problems)
            if not calls:
                times_no_tool.append(dt)
            if problems:
                failures.append(f"[{case.category}] {case.phrase} → {'; '.join(problems)}")

    for f in failures:
        print("FALHA", f)
    group_set = "validação" if options.validation else "ajuste"
    print(f"\nferramentas/{group_set} [{model}{' +files' if options.mcp else ''},persona={args.persona or 'atual'}, {args.rounds} rodada(s), "
          f"{time.time() - start_at:.0f}s]")
    for cat in totals:
        print(f"  {cat:17s} {hits[cat]:3d}/{totals[cat]:3d}  {100 * hits[cat] / totals[cat]:5.1f}%")
    total_ok, total = sum(hits.values()), sum(totals.values())
    print(f"  {'TOTAL':17s} {total_ok:3d}/{total:3d}  {100 * total_ok / total:5.1f}%")
    print(f"  afirmou sem fazer: {lies}")
    if times_no_tool:
        print(f"  tempo mediano de resposta sem ferramenta: {statistics.median(times_no_tool):.2f}s")


if __name__ == "__main__":
    main()
