"""Monitoramento (e aviões) com o modelo real e as fontes reais: função certa do agente, globo
(abrir e quadros), Estação Espacial contra rastreador público e tempo até a rádio tocar (sem som).

Uso: python -m tests.eval.monitor --model qwen2.5:14b
"""

import asyncio
import json
import math
import threading
import time
import urllib.request

from tests.eval._common import apply_model, arguments

# (pergunta, ferramenta esperada; None = nenhuma, fora do escopo)
CASES = [
    ("O que está acontecendo no Japão?", "noticias_lugar"),
    ("Quais as notícias de hoje sobre a Argentina?", "noticias_lugar"),
    ("Me conta as últimas da Nigéria.", "noticias_lugar"),
    ("Tem alguma notícia de Lisboa?", "noticias_lugar"),
    ("Como está o tempo em Tóquio?", "clima_lugar"),
    ("Vai chover amanhã em Salvador?", "clima_lugar"),
    ("Qual a temperatura agora em Moscou?", "clima_lugar"),
    ("Teve algum terremoto hoje?", "terremotos_recentes"),
    ("Houve tremores perto do Chile?", "terremotos_recentes"),
    ("Qual foi o maior terremoto das últimas horas?", "terremotos_recentes"),
    ("Quantos aviões estão voando sobre São Paulo?", "voos_lugar"),
    ("Mostra os voos sobre Londres.", "mostrar_avioes"),        # "mostra" = ver no globo
    ("Mostra os aviões sobre São Paulo.", "mostrar_avioes"),
    ("Quero ver os aviões voando sobre Nova York.", "mostrar_avioes"),
    ("Coloca os aviões de Paris no globo.", "mostrar_avioes"),
    ("Me mostra o tráfego aéreo perto do Rio de Janeiro.", "mostrar_avioes"),
    ("Liga os aviões em Tóquio.", "mostrar_avioes"),
    ("Onde está o voo GLO 1808?", "localizar_voo"),
    ("Eu quero saber onde está o voo GLO1808.", "localizar_voo"),
    ("Cadê o LA3054?", "localizar_voo"),
    ("Qual a altitude do voo GLO1808?", "localizar_voo"),          # "desse avião" with a plane selected
    ("Procura o voo AD 4500 no mapa.", "localizar_voo"),
    ("Esconde os aviões.", "esconder_avioes"),
    ("Tira os aviões da tela.", "esconder_avioes"),
    ("Desliga os aviões.", "esconder_avioes"),
    ("Some com os aviões do globo.", "esconder_avioes"),
    ("Toca uma rádio da França.", "tocar_radio"),
    ("Coloca uma rádio do Rio de Janeiro.", "tocar_radio"),
    ("Para a rádio.", "parar_radio"),
    ("Desliga essa rádio.", "parar_radio"),
    ("Onde está a Estação Espacial agora?", "satelite"),
    ("Onde está o telescópio Hubble?", "satelite"),
    ("Abre o Spotify.", None),
    ("Me lembra de pagar a conta amanhã.", None),
]


def _tool_choice(model):
    from pidreams.agent.llm import LLMAgent
    from pidreams.monitor import agent as monitor_agent

    tools = monitor_agent.MonitorAgentTools(lambda *_: None)
    ok = 0
    for question, expected in CASES:
        direct = monitor_agent.direct_command(question)      # the loop runs these by code, before the model
        if direct:
            ok += direct == expected
            print(f"{'OK   ' if direct == expected else 'FALHA'} {question!r} → {direct} por código (esperado {expected})")
            continue
        called = []

        def dispatch(name, args, called=called):
            called.append((name, args))
            return "[resultado fictício da ferramenta]"
        a = LLMAgent(system_prompt=monitor_agent.prompt(), tools=tools.schemas, dispatch=dispatch)

        async def run():
            return " ".join([s async for s in a.chat_streaming(question)])
        reply = asyncio.run(run())
        first = called[0][0] if called else None
        good = first == expected and (expected is not None or "monitoramento" in reply.lower())
        ok += good
        print(f"{'OK   ' if good else 'FALHA'} {question!r} → {called[:1]} (esperado {expected}){'' if called else ' | ' + reply[:80]}")
    print(f"\nfunção certa: {ok}/{len(CASES)} ({100 * ok / len(CASES):.0f}%)\n")


def _globe():
    import tkinter as tk

    from pidreams.monitor import satellites, sources
    from pidreams.ui import theme
    from pidreams.ui.globe import GlobeView

    root = tk.Tk()
    theme.init(root)
    root.geometry("900x720+40+40")
    t = time.perf_counter()
    g = GlobeView(root)
    g.pack(fill="both", expand=True)
    root.update()
    sats, _age = satellites.load()
    g.set_satellites(sats)
    g.set_quakes(sources.quakes())
    g.render()
    root.update()
    opened = time.perf_counter() - t
    t, n = time.perf_counter(), 30
    for _ in range(n):
        g.lon0 += 0.03
        g.render()
        root.update()
    frame = (time.perf_counter() - t) / n
    root.destroy()
    print(f"globo: aberto com {len(sats)} satélites em {opened:.1f}s; {frame * 1000:.1f} ms por quadro "
          f"({1 / frame:.0f} quadros/s)")
    return sats


def _iss(sats):
    from datetime import datetime, timezone

    ref = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://api.wheretheiss.at/v1/satellites/25544", headers={"User-Agent": "PI-dreams"}), timeout=20))
    i = sats.find("estação espacial")
    lat, lon, _alt, _ok = sats.positions(datetime.fromtimestamp(ref["timestamp"], timezone.utc))
    la, lo = math.degrees(lat[i]), math.degrees(lon[i])
    p1, p2 = math.radians(la), math.radians(ref["latitude"])
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(ref["longitude"] - lo) / 2) ** 2
    print(f"Estação Espacial: {2 * 6371 * math.asin(math.sqrt(a)):.0f} km do rastreador público\n")


def _radio():
    from pidreams.monitor import sources
    from pidreams.monitor.radio import RadioPlayer

    stations = sorted(sources.radios(), key=lambda s: -s["votes"])[:10]
    fast = 0
    for s in stations:
        started = threading.Event()
        player = RadioPlayer([None], [0.0], [True], on_change=lambda st, err, ev=started: st and ev.set())
        t = time.perf_counter()
        player.play(s)
        hit = started.wait(15) and player.station is not None
        took = time.perf_counter() - t
        player.stop()
        fast += hit and took <= 5
        print(f"{'OK   ' if hit and took <= 5 else 'LENTO' if hit else 'FALHA'} {s['name'][:35]!r}: "
              f"{f'{took:.1f}s' if hit else 'não começou em 15 s'}")
    print(f"rádio em até 5 s: {fast}/{len(stations)}")


def main():
    options = arguments(__doc__)
    model = apply_model(options.model)
    start = time.time()
    _tool_choice(model)
    sats = _globe()
    _iss(sats)
    _radio()
    print(f"\nmonitoramento [{model}] em {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
