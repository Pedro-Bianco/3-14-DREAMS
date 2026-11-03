"""The monitor's agent: same chat model, its own prompt and only the monitor's tools.

With 7 tools instead of the app's ~30 it has less to choose from; tools that name a place also
turn the globe there (event monitor_focus). Closing the monitor is handled by code in the loop,
never left to the model (same rule as cancelling a shutdown).
"""

import math

from pidreams.core.settings import SETTINGS
from pidreams.monitor import sources, world

CLOSE_PHRASES = {"fechar monitoramento", "fecha o monitoramento", "fechar o monitoramento", "sair do monitoramento",
                 "fecha monitoramento", "encerrar monitoramento", "voltar ao normal"}


OPEN_PHRASES = {"monitoramento", "abre o monitoramento", "abra o monitoramento", "abrir monitoramento",
                "abrir o monitoramento", "abre monitoramento", "modo monitoramento", "entrar no monitoramento",
                "mostra o globo", "abre o globo"}


def _phrase(text: str) -> str:
    return " ".join(text.lower().strip(" .,!?").split())


def is_close_request(text: str) -> bool:
    return _phrase(text) in CLOSE_PHRASES


def is_open_request(text: str) -> bool:
    """Opening is decided by code too: asked by voice, the normal agent said it knew no such app."""
    return _phrase(text) in OPEN_PHRASES


def prompt() -> str:
    name = SETTINGS.get("assistant_name") or "PI dreams"
    treatment = SETTINGS.get("treatment")
    # Measured: "Você é o X no modo Y. Trate o usuário por Z." at the top made qwen2.5:14b answer in
    # Thai or loop until Ollama aborted; "em modo de ..." with the form of address at the end did not.
    address = f"\nChame o usuário de {treatment}." if treatment else ""
    return (f"Você é o {name}, assistente de voz, agora em modo de monitoramento, com um globo da Terra na tela.\n"
            "Fale em português do Brasil, em frases curtas (a resposta é falada).\n"
            "Você só trata de: notícias de um lugar, clima, terremotos, voos, rádios e satélites. Use as "
            "ferramentas para isso, uma por pedido, sempre com o lugar que o usuário disse.\n"
            "Notícias: resuma em 2 a 4 frases SÓ as manchetes recebidas e diga de quais veículos vieram. "
            "Nunca invente notícia, número ou fato que não veio da ferramenta.\n"
            "Se pedirem outra coisa (abrir programas, lembretes, e-mail, conversa geral), diga que no "
            "Monitoramento você só cuida disso e que, para o resto, é só fechar o Monitoramento." + address)


def _tool(name: str, description: str, params: dict | None = None, required: tuple = ()) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": params or {}, "required": list(required)}}}


_PLACE = {"lugar": {"type": "string", "description": "País, cidade ou região, como o usuário disse (ex.: Japão, Lagos)."}}

SCHEMAS = [
    _tool("noticias_lugar", "Notícias recentes de um país, cidade ou região. Use quando o usuário "
          "perguntar o que está acontecendo num lugar ou pedir notícias de lá.", _PLACE, ("lugar",)),
    _tool("clima_lugar", "Clima agora e previsão de 3 dias de um lugar.", _PLACE, ("lugar",)),
    _tool("terremotos_recentes", "Terremotos de magnitude 2,5 ou mais nas últimas 24 h, no mundo ou perto de um lugar.",
          {"lugar": {"type": "string", "description": "Lugar opcional; vazio = o mundo todo."}}),
    _tool("voos_lugar", "Aviões voando agora sobre um lugar (raio de ~250 km).", _PLACE, ("lugar",)),
    _tool("tocar_radio", "Toca uma rádio ao vivo de um lugar.", _PLACE, ("lugar",)),
    _tool("parar_radio", "Para a rádio que está tocando."),
    _tool("satelite", "Onde está um satélite agora (ex.: Estação Espacial, Hubble, um Starlink).",
          {"nome": {"type": "string", "description": "Nome do satélite; 'Estação Espacial' para a ISS."}}, ("nome",)),
]


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


class MonitorAgentTools:
    """Tools and dispatch for LLMAgent(tools=..., dispatch=...)."""

    def __init__(self, emit, radio=None, satellites=lambda: None):
        self._emit, self._radio, self._satellites = emit, radio, satellites

    def schemas(self) -> list[dict]:
        return SCHEMAS

    def dispatch(self, name: str, args: dict) -> str:
        handler = getattr(self, "_" + name, None)
        if handler is None:
            return f"[Erro] Ferramenta desconhecida: {name}."
        missing = [p for p in next(s for s in SCHEMAS if s["function"]["name"] == name)["function"]["parameters"]["required"]
                   if not str(args.get(p, "")).strip()]
        if missing:
            return f"[Erro] A chamada de '{name}' veio sem {', '.join(missing)}. Chame de novo preenchendo: {', '.join(missing)}."
        try:
            return handler(**{k: v for k, v in args.items() if isinstance(v, str)})
        except sources.SourceError as e:
            return str(e)

    def _locate(self, lugar: str) -> dict:
        # A country is the country, not a city search: "Brasil" came back as Brasília.
        country = world.country_by_name(lugar)
        if country:
            p = {"name": country["name"], "country": country["name"], "lat": country["lat"], "lon": country["lon"]}
        else:
            p = sources.place(lugar)
        self._emit("monitor_focus", {"lat": p["lat"], "lon": p["lon"], "name": p["name"]})
        return p

    def _noticias_lugar(self, lugar: str) -> str:
        p = self._locate(lugar)
        query = p["name"] if p["name"] == p["country"] else f"{p['name']} {p['country']}"
        items = sources.news(query)
        if not items:
            return f"Não encontrei notícias recentes sobre {p['name']}."
        lines = "\n".join(f"- {i['title']} ({i['source']}{', ' + i['date'] if i['date'] else ''})" for i in items)
        return f"Manchetes das últimas 24 h sobre {p['name']}:\n{lines}\nResuma citando os veículos."

    def _clima_lugar(self, lugar: str) -> str:
        p = self._locate(lugar)
        w = sources.weather(p["lat"], p["lon"])
        days = "; ".join(f"{d['date'][8:]}/{d['date'][5:7]}: {d['desc']}, {d['min']:.0f} a {d['max']:.0f} °C, chuva {d['rain']}%"
                         for d in w["days"])
        return (f"{p['name']} ({p['country']}): agora {w['now']['temp']:.0f} °C, {w['now']['desc']}, "
                f"vento {w['now']['wind']:.0f} km/h. Próximos dias: {days}.")

    def _terremotos_recentes(self, lugar: str = "") -> str:
        quakes = sources.quakes()
        where = "no mundo"
        if lugar.strip():
            p = self._locate(lugar)
            quakes = [q for q in quakes if _distance_km(p["lat"], p["lon"], q["lat"], q["lon"]) <= 1500]
            where = f"perto de {p['name']}"
        if not quakes:
            return f"Nenhum terremoto de magnitude 2,5 ou mais nas últimas 24 h {where}."
        if not lugar.strip():
            self._emit("monitor_focus", {"lat": quakes[0]["lat"], "lon": quakes[0]["lon"], "name": quakes[0]["place"]})
        lines = "\n".join(f"- magnitude {q['mag']:.1f}, {q['place']}, {q['depth']:.0f} km de profundidade" for q in quakes[:6])
        return f"{len(quakes)} terremotos nas últimas 24 h {where}; os mais fortes:\n{lines}"

    def _voos_lugar(self, lugar: str) -> str:
        p = self._locate(lugar)
        planes = sources.flights(p["lat"], p["lon"])
        if not planes:
            return f"Nenhum avião detectado agora num raio de ~250 km de {p['name']}."
        high = sorted((a for a in planes if isinstance(a["alt"], (int, float))), key=lambda a: -a["alt"])[:6]
        lines = ", ".join(f"{a['callsign'] or '?'} a {a['alt'] * 0.3048:,.0f} m".replace(",", ".") for a in high)
        return f"{len(planes)} aeronaves agora num raio de ~250 km de {p['name']}. Exemplos: {lines}."

    def _tocar_radio(self, lugar: str) -> str:
        if self._radio is None:
            return "O tocador de rádio não está disponível."
        p = self._locate(lugar)
        stations = sources.radios()
        near = [s for s in stations if _distance_km(p["lat"], p["lon"], s["lat"], s["lon"]) <= 400]
        if not near:
            return f"Não achei rádios MP3 perto de {p['name']}."
        # The most popular first; one that does not answer (403, off the air) gives way to the next.
        station = self._radio.play(sorted(near, key=lambda s: -s["votes"]), wait_s=20)
        if station is None:
            return f"Nenhuma rádio perto de {p['name']} respondeu agora."
        return f"Tocando {station['name']} ({station['country']})."

    def _parar_radio(self) -> str:
        if self._radio is None or self._radio.station is None:
            return "Nenhuma rádio está tocando."
        self._radio.stop()
        return "Rádio parada."

    def _satelite(self, nome: str) -> str:
        sats = self._satellites()
        if sats is None:
            return "Os satélites ainda estão carregando; tente de novo em instantes."
        i = sats.find(nome)
        if i is None:
            return f"Não achei um satélite chamado “{nome}”."
        lat, lon, alt, ok = sats.positions()
        if not ok[i]:
            return f"Não consegui calcular a posição de {sats.names[i]} agora."
        la, lo = math.degrees(lat[i]), math.degrees(lon[i])
        self._emit("monitor_focus", {"lat": la, "lon": lo, "name": sats.names[i], "satellite": i})
        country = world.country_at(la, lo)
        over = f"sobre {country['name']}" if country else "sobre o oceano"
        return f"{sats.names[i]} ({sats.owners[i]}) está a {alt[i]:.0f} km de altitude, {over} (lat {la:.1f}, lon {lo:.1f})."
