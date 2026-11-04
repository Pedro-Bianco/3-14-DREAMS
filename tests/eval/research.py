"""Pesquisa profunda com o modelo e as fontes reais: tempo, fontes, fontes listadas x lidas,
citações válidas e uma amostra de afirmações para conferência manual. Nada é guardado na Base.

Uso: python -m tests.eval.research --model qwen2.5:14b
"""

import re
import threading
import time

from tests.eval._common import apply_model, arguments

TOPICS = ["baterias de íon de sódio", "a Grande Barreira de Corais", "computação quântica", "a história do Pix no Brasil",
          "o telescópio James Webb"]


def main():
    from pidreams.research.agent import chat
    from pidreams.research.job import ResearchJob

    options = arguments(__doc__)
    model = apply_model(options.model)
    fast = rich = honest = valid = 0
    for topic in TOPICS:
        done = threading.Event()
        j = ResearchJob(topic, chat, on_progress=lambda s, d=done: s["etapa"] in ("pronta", "cancelada", "falhou") and d.set(),
                        save=lambda t, r: ("(não guardado)", None))
        t = time.time()
        j.start()
        done.wait(900)
        took = time.time() - t
        listed = [s for s in j.sources if s.get("n")]
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", j.report.split("## Fontes")[0])}
        ok_time, ok_rich = took <= 180, len(listed) >= 4
        ok_honest = all(s.get("ok") for s in listed)
        ok_valid = cited <= {s["n"] for s in listed}
        fast, rich, honest, valid = fast + ok_time, rich + ok_rich, honest + ok_honest, valid + ok_valid
        print(f"{topic!r}: {took:.0f}s ({'ok' if ok_time else 'LENTO'}), {len(listed)} fontes, "
              f"lidas {'100%' if ok_honest else 'NÃO'}, citações {'válidas' if ok_valid else 'INVÁLIDAS'}, "
              f"estado {j.state}")
        sample = [line.strip() for line in j.report.splitlines() if re.search(r"\[\d+\]", line)][:2]
        for line in sample:
            print(f"    amostra: {line[:220]}")
        for s in listed:
            print(f"    [{s['n']}] {s['title'][:60]} — {s['url'][:70]}")
    n = len(TOPICS)
    print(f"\npesquisa [{model}]: até 3 min {fast}/{n}; ≥ 4 fontes {rich}/{n}; fontes lidas {honest}/{n}; "
          f"citações válidas {valid}/{n}")


if __name__ == "__main__":
    main()
