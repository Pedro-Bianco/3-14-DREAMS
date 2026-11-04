"""Ações no PC com o modelo real: ferramenta e argumentos certos, e nada em conversa.

As ferramentas de PC NÃO rodam: a chamada é registrada e devolve um resultado plausível (nada muda
no computador). Confere a ação e o alvo certos, e que conversa que só cita volume, janela
ou desligar não chama nada.
Uso: python -m tests.eval.pc_actions --model qwen2.5:14b [--rounds 2]
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field

from tests.eval._common import apply_model, arguments

_FAKE = {
    "mudar_volume": "Volume em 40%.", "silenciar": "Som mudo.", "controlar_musica": "Mandei pausar o que está tocando.",
    "ver_janelas": "Abertos: Chrome, VS Code, Bloco de Notas.", "mexer_janela": "Chrome em primeiro plano.",
    "minimizar_tudo": "Janelas minimizadas.", "fechar_app": "Pedi para fechar o Bloco de Notas.",
    "mudar_brilho": "Brilho em 40%.", "desligar_pc": "O PC desliga às 23:41.", "bloquear_pc": "PC bloqueado.",
    "reiniciar_pc": "O PC reinicia às 23:41.",
    "cancelar_desligamento": "Desligamento cancelado.",
}


@dataclass
class Case:
    phrase: str
    tool: str | None                 # None = não deve chamar ferramenta de PC
    category: str
    args: dict = field(default_factory=dict)     # campo -> valor esperado (texto: trecho, sem caixa)


CASES = [
    Case("Abaixa o volume.", "mudar_volume", "volume", {"direcao": "menos"}),
    Case("Aumenta o som aí.", "mudar_volume", "volume", {"direcao": "mais"}),
    Case("Coloca o volume em 30.", "mudar_volume", "volume", {"valor": 30}),
    Case("Volume no máximo.", "mudar_volume", "volume", {"valor": 100}),
    Case("Muta o computador.", "silenciar", "volume", {"mudo": True}),
    Case("Tira do mudo.", "silenciar", "volume", {"mudo": False}),
    Case("Pausa a música.", "controlar_musica", "musica", {"comando": "pausar"}),
    Case("Pode continuar o vídeo.", "controlar_musica", "musica", {"comando": "continuar"}),
    Case("Pula essa música.", "controlar_musica", "musica", {"comando": "proxima"}),
    Case("Volta a música anterior.", "controlar_musica", "musica", {"comando": "anterior"}),
    Case("Quais programas estão abertos?", "ver_janelas", "janelas"),
    Case("O que tem aberto no PC agora?", "ver_janelas", "janelas"),
    Case("Traz o Chrome pra frente.", "mexer_janela", "janelas", {"app": "chrome", "como": "frente"}),
    Case("Minimiza o Spotify.", "mexer_janela", "janelas", {"app": "spotify", "como": "minimizar"}),
    Case("Maximiza o VS Code.", "mexer_janela", "janelas", {"app": "code", "como": "maximizar"}),
    Case("Minimiza tudo.", "minimizar_tudo", "janelas"),
    Case("Mostra a área de trabalho.", "minimizar_tudo", "janelas"),
    Case("Fecha o Bloco de Notas.", "fechar_app", "fechar", {"app": "bloco"}),
    Case("Pode fechar o Discord.", "fechar_app", "fechar", {"app": "discord"}),
    Case("Aumenta o brilho da tela.", "mudar_brilho", "brilho", {"direcao": "mais"}),
    Case("Brilho em 40.", "mudar_brilho", "brilho", {"valor": 40}),
    Case("Diminui o brilho.", "mudar_brilho", "brilho", {"direcao": "menos"}),
    Case("Bloqueia o PC.", "bloquear_pc", "energia"),
    Case("Desliga o computador.", "desligar_pc", "energia"),
    Case("Desliga o PC daqui a 10 minutos.", "desligar_pc", "energia", {"minutos": 10}),
    Case("Reinicia o computador.", "reiniciar_pc", "energia"),
    Case("Cancela o desligamento.", "cancelar_desligamento", "energia"),
    Case("O volume daquele show ontem estava altíssimo.", None, "nao_chamar"),
    Case("Que música você acha que combina com chuva?", None, "nao_chamar"),
    Case("Minha janela do quarto está quebrada.", None, "nao_chamar"),
    Case("O brilho do sol hoje está forte, né?", None, "nao_chamar"),
    Case("Eu desliguei o celular para dormir melhor.", None, "nao_chamar"),
    Case("Como faço para fechar um negócio com um cliente?", None, "nao_chamar"),
    Case("Qual a diferença entre maximizar e otimizar?", None, "nao_chamar"),
    Case("Me explica o que é um programa de computador.", None, "nao_chamar"),
    Case("Reiniciar a vida em outra cidade é uma boa ideia?", None, "nao_chamar"),
]


def _ok_arg(expected, got) -> bool:
    if isinstance(expected, bool):
        return got is expected or str(got).lower() == str(expected).lower()
    if isinstance(expected, (int, float)):
        try:
            return float(got) == float(expected)
        except (TypeError, ValueError):
            return False
    return str(expected).lower() in str(got or "").lower()


async def _turn(phrase: str) -> list[tuple[str, dict]]:
    from pidreams import pc
    from pidreams.agent import llm as llm_module
    from pidreams.agent import tools

    calls: list[tuple[str, dict]] = []
    real = llm_module.dispatch_tool

    def dispatch(name, args):
        # Same recovery as the app: a call missing a required argument gets the real error back
        # and the model calls again; only the corrected call counts.
        missing = tools._missing_arguments(name, args)
        if missing:
            return real(name, args)
        calls.append((name, args))
        return _FAKE.get(name, "[resultado fictício]")

    llm_module.dispatch_tool = dispatch
    try:
        agent = llm_module.LLMAgent()
        _ = [f async for f in agent.chat_streaming(phrase)]
    finally:
        llm_module.dispatch_tool = real
    return [(n, a) for n, a in calls if n in pc.FUNCTIONS]


def _check(case: Case, calls: list[tuple[str, dict]]) -> list[str]:
    if case.tool is None:
        return [f"chamou {calls[0][0]}"] if calls else []
    chosen = [a for n, a in calls if n == case.tool]
    if not chosen:
        return [f"chamou {[n for n, _ in calls] or 'nada'}, esperado {case.tool}"]
    args = chosen[0]
    return [f"{k}={args.get(k)!r}, esperado {v!r}" for k, v in case.args.items() if not _ok_arg(v, args.get(k))]


def main():
    options = arguments("Ações no PC")
    model = apply_model(options.model)
    start = time.time()
    by_category: dict[str, list[bool]] = defaultdict(list)
    for _ in range(options.rounds):
        for case in CASES:
            try:
                errors = _check(case, asyncio.run(_turn(case.phrase)))
            except Exception as e:                       # e.g. Ollama aborting a repetition loop
                errors = [f"erro: {str(e)[:80]}"]
            by_category[case.category].append(not errors)
            if errors:
                print(f"FALHA [{case.category}] {case.phrase} → {'; '.join(errors)}")
    print(f"\nacoes_pc [{model}, {options.rounds} rodada(s), {time.time() - start:.0f}s]")
    hits = total = 0
    for category, results in by_category.items():
        hits, total = hits + sum(results), total + len(results)
        print(f"  {category:12s} {sum(results):3d}/{len(results):3d}  {100 * sum(results) / len(results):5.1f}%")
    print(f"  TOTAL        {hits:3d}/{total:3d}  {100 * hits / total:5.1f}%")


if __name__ == "__main__":
    main()
