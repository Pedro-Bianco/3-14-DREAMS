"""Pedidos de lembrete com o modelo real.

Turno completo do agente com as ferramentas de lembrete de verdade, num LOCALAPPDATA temporário por
caso. Confere o que ficou guardado (data e hora esperadas calculadas aqui, sem usar o resolvedor) e
que frases com "lembrar" que não são lembrete não guardam nada. Outras ferramentas: resultado falso.
Uso: python -m tests.eval.reminders --model qwen2.5:14b
"""

import asyncio
import datetime as dt
import os
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass

from tests.eval._common import apply_model, arguments

TODAY = dt.date.today()
NOW = dt.datetime.now()


def _next(weekday: int) -> dt.date:                 # nunca hoje (regra dos lembretes)
    return TODAY + dt.timedelta(days=(weekday - TODAY.weekday()) % 7 or 7)


def _next_day_of_month(day: int) -> dt.date:
    data = TODAY.replace(day=1)
    while True:
        try:
            target = data.replace(day=day)
            if target >= TODAY:
                return target
        except ValueError:
            pass
        data = (data + dt.timedelta(days=32)).replace(day=1)


@dataclass
class Case:
    phrase: str
    category: str
    data: dt.date | None = None            # esperada (criar)
    hour: str | None = None
    word: str = ""                      # trecho que precisa estar no texto guardado
    before: tuple = ()                      # lembretes que já existem: (texto, quando)
    some: str = ""                         # concluir/apagar: este lembrete sai dos pendentes


TOMORROW = TODAY + dt.timedelta(days=1)
CASES = [
    Case("Me lembra de pagar a conta de luz amanhã.", "criar", TOMORROW, None, "luz"),
    Case("Me lembra na sexta de levar o carro na revisão.", "criar", _next(4), None, "carro"),
    Case("Me lembra dia 12 da consulta no dentista.", "criar", _next_day_of_month(12), None, "dentista"),
    Case("Daqui a 3 dias me lembra de devolver o livro.", "criar", TODAY + dt.timedelta(days=3), None, "livro"),
    Case("Me lembra semana que vem de renovar o seguro.", "criar", TODAY + dt.timedelta(days=7 - TODAY.weekday()), None, "seguro"),
    Case("Me lembra amanhã às 15h de ligar para a escola.", "criar", TOMORROW, "15:00", "escola"),
    Case("Me lembra segunda de manhã de mandar o relatório.", "criar", _next(0), "09:00", "relat"),
    Case("Lembra-me depois de amanhã de comprar ração.", "criar", TODAY + dt.timedelta(days=2), None, "ra"),
    Case("Me avisa no dia 25 de dezembro de ligar para a vó.", "criar",
         dt.date(TODAY.year if (12, 25) >= (TODAY.month, TODAY.day) else TODAY.year + 1, 12, 25), None, "v"),
    Case("Coloca um lembrete para quarta: buscar as fotos.", "criar", _next(2), None, "foto"),
    Case("Não me deixa esquecer de regar as plantas amanhã.", "criar", TOMORROW, None, "planta"),
    Case("Me lembra de comprar pão.", "sem_data"),
    Case("Quais lembretes eu tenho?", "listar", before=(("pagar o IPVA", "sexta"),)),
    Case("Tenho algum lembrete pendente?", "listar", before=(("cortar o cabelo", "amanhã"),)),
    Case("Já paguei a conta de luz.", "concluir", before=(("pagar a conta de luz", "amanhã"),), some="luz"),
    Case("Pode tirar o lembrete da escola.", "apagar", before=(("ligar para a escola", "sexta"),), some="escola"),
    Case("Apaga o lembrete do dentista.", "apagar", before=(("consulta no dentista", "dia 12"),), some="dentista"),
    Case("Lembra quando fomos à praia no verão?", "nao_criar"),
    Case("Você lembra o meu nome?", "nao_criar"),
    Case("O que é um lembrete?", "nao_criar"),
    Case("Me conta uma piada curta.", "nao_criar"),
]


async def _turn(case: Case) -> tuple[list[str], str]:
    from pidreams import reminders
    from pidreams.agent import llm as llm_module
    from pidreams.agent import tools

    for text, quando in case.before:
        reminders.create(text, quando, NOW)
    calls: list[str] = []
    real_dispatch = tools.dispatch_tool

    def dispatch(name, args):
        calls.append(name)
        return real_dispatch(name, args) if name in reminders.FUNCTIONS else "[resultado fictício]"

    llm_module.dispatch_tool = dispatch
    try:
        agent = llm_module.LLMAgent()
        reply = " ".join([f async for f in agent.chat_streaming(case.phrase)])
    finally:
        llm_module.dispatch_tool = real_dispatch
    return calls, reply


def _check(case: Case, calls: list[str], reply: str) -> list[str]:
    from pidreams import reminders

    pending = reminders.pending_items()
    new_items = [l for l in pending if not any(l["texto"] == t for t, _ in case.before)]
    errors = []
    if case.category == "criar":
        if len(new_items) != 1:
            return [f"{len(new_items)} lembrete(s) guardado(s)"]
        l = new_items[0]
        if l["data"] != case.data.isoformat():
            errors.append(f"data {l['data']} (esperado {case.data.isoformat()})")
        if (l.get("hora") or None) != case.hour:
            errors.append(f"hora {l.get('hora')} (esperado {case.hour})")
        if case.word.lower() not in l["texto"].lower():
            errors.append(f"texto {l['texto']!r}")
    elif case.category in ("sem_data", "nao_criar"):
        if new_items:
            errors.append(f"guardou {new_items[0]['texto']!r}")
        if case.category == "nao_criar" and set(calls) & set(reminders.FUNCTIONS):
            errors.append("chamou a ferramenta")
    elif case.category == "listar":
        if "ver_lembretes" not in calls:
            errors.append("não consultou os lembretes")
        if case.before[0][0].split()[-1].lower() not in reply.lower():
            errors.append("resposta sem o lembrete")
    elif any(case.some in l["texto"] for l in pending):
        errors.append(f"o lembrete de {case.some!r} continua pendente")
    return errors


def main():
    from pidreams.core.settings import SETTINGS

    args = arguments(__doc__)
    model = apply_model(args.model)
    SETTINGS.set("treatment", "chefe")             # só em memória: fictício e reproduzível
    hits, totals, failures = defaultdict(int), defaultdict(int), []
    start_at = time.time()
    for _ in range(args.rounds):
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix="pid-lembretes-") as folder:
                os.environ["LOCALAPPDATA"] = folder            # lembretes.json só deste caso
                calls, reply = asyncio.run(_turn(case))
                errors = _check(case, calls, reply)
            totals[case.category] += 1
            hits[case.category] += not errors
            if errors:
                failures.append(f"[{case.category}] {case.phrase} → {'; '.join(errors)}")
    for f in failures:
        print("FALHA", f)
    print(f"\nlembretes [{model}, {args.rounds} rodada(s), {time.time() - start_at:.0f}s]")
    for cat in totals:
        print(f"  {cat:10s} {hits[cat]:3d}/{totals[cat]:3d}")
    ok, total = sum(hits.values()), sum(totals.values())
    print(f"  {'TOTAL':10s} {ok:3d}/{total:3d}  {100 * ok / total:5.1f}%")


if __name__ == "__main__":
    main()
