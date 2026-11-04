"""Monitoramento: mundo, fontes (respostas gravadas fictícias, sem rede), satélites,
agente (ferramentas e fechar por código), rádio e desenho do globo."""

import asyncio
import json
import math

import numpy as np
import pytest

from pidreams.monitor import agent, satellites, sources, world


# ── mundo ──

@pytest.mark.parametrize("lat,lon,name", [(-23.5, -46.6, "Brasil"), (35.7, 139.7, "Japão"), (48.8, 2.3, "França"),
                                          (-33.9, 151.2, "Austrália"), (0.0, -30.0, None)])
def test_pais_sob_o_ponto(lat, lon, name):
    found = world.country_at(lat, lon)
    assert (found["name"] if found else None) == name


def test_pais_pelo_nome_sem_acento():
    jp = world.country_by_name("japao")
    assert jp["iso"] == "JP" and 30 < jp["lat"] < 45 and 128 < jp["lon"] < 146
    assert world.country_by_name("Atlântida") is None


def test_pais_nao_vira_cidade(monkeypatch):
    monkeypatch.setattr(sources, "place", lambda n: (_ for _ in ()).throw(AssertionError("não devia buscar cidade")))
    monkeypatch.setattr(sources, "news", lambda q: [{"title": "T", "source": "S", "date": "", "link": ""}])
    events = []
    reply = agent.MonitorAgentTools(lambda e, d: events.append(d["name"])).dispatch("noticias_lugar", {"lugar": "Brasil"})
    assert "sobre Brasil" in reply and events == ["Brasil"]


def test_resposta_em_outra_escrita_e_detectada():
    from pidreams.agent.llm import _foreign_script
    assert _foreign_script("คณะกรรมการทำงานของฉันคือการติดตามข่าวสาร")
    assert _foreign_script("我会帮你查看新闻和天气情况")
    assert not _foreign_script("As notícias de hoje sobre o Brasil são estas, segundo a Agência Brasil.")


# ── fontes (respostas gravadas) ──

RSS = """<rss><channel>
<item><title>Chuvas fortes atingem o litoral do Japão</title><link>https://exemplo.com/1</link>
<description>&lt;p&gt;Tóquio em alerta&lt;/p&gt;</description><pubDate>Mon, 02 Nov 2026 12:30:00 GMT</pubDate></item>
<item><title>Eleição local tem segundo turno</title><link>https://exemplo.com/2</link>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>""".encode("utf-8")
RDF = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<item><title>Japão anuncia plano</title><link>https://exemplo.org/3</link><dc:date>2026-11-02T15:00:00Z</dc:date></item>
</rdf:RDF>""".encode("utf-8")


def test_feeds_rss_e_rdf_e_filtro_pelo_lugar():
    items = sources.parse_feed(RSS, "Jornal Exemplo") + sources.parse_feed(RDF, "Rádio Fictícia")
    assert items[0]["summary"] == "Tóquio em alerta" and items[0]["date"] == "02/11 12:30"
    assert items[2]["date"] == "02/11 15:00"
    found = sources.matching(items, "Japao")                  # accents ignored
    assert [i["title"] for i in found] == ["Japão anuncia plano", "Chuvas fortes atingem o litoral do Japão"]
    assert sources.matching(items, "Coreia") == []


def test_monitor_fala_so_com_os_feeds_e_a_pesquisa_cai_para_o_gdelt(monkeypatch, tmp_path):
    monkeypatch.setattr(sources.paths, "cache_dir", lambda _k: tmp_path)
    monkeypatch.setattr(sources, "_GDELT_GAP_S", 0)
    gdelt = json.dumps({"articles": [{"title": "Notícia reserva", "domain": "exemplo.net", "seendate": "20261102T1200Z",
                                      "url": "https://exemplo.net/a"}]}).encode()
    calls = []

    def fake_get(url, timeout=15):
        calls.append(url)
        return gdelt if "gdeltproject" in url else RSS
    monkeypatch.setattr(sources, "_get", fake_get)
    assert sources.news("Japão")[0]["link"] == "https://exemplo.com/1"       # the feeds have it (once)
    assert sources.news("Lugar Exemplo") == []                              # the monitor never waits for GDELT
    assert not any("gdeltproject" in c for c in calls)
    assert sources.news_about("Lugar Exemplo")[0]["source"] == "exemplo.net"   # the research does: GDELT
    assert sum("gdeltproject" in c for c in calls) == 1


def test_terremotos_voos_e_radios():
    quakes = sources.parse_quakes(json.dumps({"features": [
        {"geometry": {"coordinates": [10, 20, 5]}, "properties": {"place": "A", "mag": 3.1, "time": 1000}},
        {"geometry": {"coordinates": [11, 21, 9]}, "properties": {"place": "B", "mag": 5.0, "time": 2000}}]}).encode())
    assert [q["place"] for q in quakes] == ["B", "A"]
    planes = sources.parse_flights(json.dumps({"ac": [{"flight": "ABC123 ", "lat": 1, "lon": 2, "alt_baro": 30000},
                                                      {"hex": "x"}]}).encode())
    assert planes == [{"callsign": "ABC123", "lat": 1, "lon": 2, "alt": 30000, "speed": None, "type": ""}]
    radios = sources.parse_radios(json.dumps([
        {"name": " Rádio Um ", "country": "Brasil", "countrycode": "BR", "geo_lat": -23, "geo_long": -46,
         "url_resolved": "http://exemplo/um.mp3", "codec": "MP3", "clickcount": 9},
        {"name": "Rádio AAC", "geo_lat": 1, "geo_long": 1, "url": "http://x", "codec": "AAC"},
        {"name": "Sem lugar", "geo_lat": None, "geo_long": None, "url": "http://y", "codec": "MP3"}]).encode())
    assert [r["name"] for r in radios] == ["Rádio Um"]


def test_radios_tentam_o_proximo_servidor_e_se_identificam(monkeypatch):
    monkeypatch.setattr(sources, "radio_servers", lambda: ["a.exemplo", "b.exemplo"])
    asked = []

    def get(url, timeout=15):
        asked.append(url.split("/")[2])
        if "a.exemplo" in url:
            raise OSError("fora do ar")
        return json.dumps([{"name": "Rádio Um", "geo_lat": 1, "geo_long": 2, "url": "http://x", "codec": "MP3"}]).encode()

    monkeypatch.setattr(sources, "_get", get)
    assert [r["name"] for r in sources._fetch_radios()] == ["Rádio Um"]
    assert asked == ["a.exemplo", "b.exemplo"]
    assert sources._AGENT["User-Agent"].startswith("PI-dreams/")          # a clear name, not a browser's


def test_cache_usa_copia_antiga_quando_a_fonte_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.paths, "cache_dir", lambda _k: tmp_path)
    assert sources._cached("x", 60, lambda: [1, 2], "x")[0] == [1, 2]
    import os
    os.utime(tmp_path / "x.json", (0, 0))                       # very old copy
    data, age = sources._cached("x", 60, lambda: (_ for _ in ()).throw(OSError("403")), "x")
    assert data == [1, 2] and age > 60
    with pytest.raises(sources.SourceError):
        sources._cached("nada", 60, lambda: (_ for _ in ()).throw(OSError("sem rede")), "os dados")


# ── satélites ──

ISS_OMM = {"OBJECT_NAME": "ISS (ZARYA)", "OBJECT_ID": "1998-067A", "EPOCH": "2026-11-02T12:00:00.000000",
           "MEAN_MOTION": 15.5, "ECCENTRICITY": 0.0006, "INCLINATION": 51.64, "RA_OF_ASC_NODE": 100.0,
           "ARG_OF_PERICENTER": 50.0, "MEAN_ANOMALY": 300.0, "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U",
           "NORAD_CAT_ID": 25544, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 50000, "BSTAR": 0.0002,
           "MEAN_MOTION_DOT": 0.0001, "MEAN_MOTION_DDOT": 0}


def test_tipos_pelo_nome():
    assert satellites.kind_of("STARLINK-1234") == "internet"
    assert satellites.kind_of("GPS BIIF-2") == "outros" or satellites.kind_of("NAVSTAR 80") == "navegacao"
    assert satellites.kind_of("NOAA 19") == "clima" and satellites.kind_of("ISS (ZARYA)") == "estacao"


def test_posicao_e_altitude_da_estacao():
    from datetime import datetime, timezone
    sats = satellites.Satellites([ISS_OMM], {"25544": "ISS"})
    lat, lon, alt, ok = sats.positions(datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    assert ok[0] and 380 < alt[0] < 460 and abs(math.degrees(lat[0])) <= 52
    assert sats.find("estação espacial") == 0 and sats.owners[0].startswith("Estação Espacial")


# ── agente ──

def test_abrir_e_fechar_monitoramento_sao_decididos_pelo_codigo():
    assert agent.is_close_request("Fechar monitoramento!") and not agent.is_close_request("fechar o spotify")
    assert agent.is_open_request("Abra o monitoramento.") and not agent.is_open_request("abra o spotify")


def test_ferramenta_sem_lugar_pede_de_novo_e_lugar_gira_o_globo(monkeypatch):
    events = []
    tools = agent.MonitorAgentTools(lambda e, d: events.append((e, d["name"])))
    assert "veio sem lugar" in tools.dispatch("noticias_lugar", {})
    monkeypatch.setattr(sources, "place", lambda n: {"name": "Cidade Exemplo", "country": "País Exemplo", "lat": 1.0, "lon": 2.0})
    monkeypatch.setattr(sources, "news", lambda q: [{"title": "Manchete fictícia", "source": "Jornal Exemplo", "date": "", "link": ""}])
    reply = tools.dispatch("noticias_lugar", {"lugar": "Cidade Exemplo"})
    assert "Manchete fictícia (Jornal Exemplo)" in reply and events == [("monitor_focus", "Cidade Exemplo")]


def test_erro_de_fonte_vira_frase_para_o_usuario(monkeypatch):
    def fail(_n):
        raise sources.SourceError("Não consegui localizar o lugar agora (sem conexão?).")
    monkeypatch.setattr(sources, "place", fail)
    tools = agent.MonitorAgentTools(lambda *_: None)
    assert tools.dispatch("clima_lugar", {"lugar": "X"}).startswith("Não consegui")


def test_radio_mais_popular_perto_do_lugar(monkeypatch):
    played = []

    class Player:
        station = None

        def play(self, stations, wait_s=0):
            played.append(stations[0]["name"])
            return stations[0]
    monkeypatch.setattr(sources, "place", lambda n: {"name": "Cidade Exemplo", "country": "País", "lat": 0.0, "lon": 0.0})
    monkeypatch.setattr(sources, "radios", lambda: [
        {"name": "Perto", "country": "País", "lat": 1, "lon": 1, "url": "u", "votes": 5},
        {"name": "Perto popular", "country": "País", "lat": 0.5, "lon": 0.5, "url": "u", "votes": 50},
        {"name": "Longe", "country": "Outro", "lat": 40, "lon": 40, "url": "u", "votes": 999}])
    tools = agent.MonitorAgentTools(lambda *_: None, radio=Player())
    assert tools.dispatch("tocar_radio", {"lugar": "Cidade Exemplo"}) == "Tocando Perto popular (País)." and played == ["Perto popular"]


def test_radio_que_nao_responde_passa_para_a_proxima(monkeypatch):
    from pidreams.monitor import radio

    class Fail:
        def __init__(self, url):
            raise OSError("HTTP Error 403: Forbidden")
    monkeypatch.setattr(radio, "_source_class", lambda: Fail)
    changes = []
    player = radio.RadioPlayer([None], [1.0], [True], on_change=lambda s, e: changes.append(e))
    assert player.play([{"name": "A", "url": "u"}, {"name": "B", "url": "u"}], wait_s=5) is None
    assert changes == ["Nenhuma rádio respondeu agora."]


def test_agente_com_ferramentas_proprias_nao_ve_as_do_app():
    from pidreams.agent.llm import LLMAgent
    tools = agent.MonitorAgentTools(lambda *_: None)
    a = LLMAgent(system_prompt="monitor", tools=tools.schemas, dispatch=tools.dispatch)
    names = {s["function"]["name"] for s in a._tool_schemas()}
    assert names == {"noticias_lugar", "clima_lugar", "terremotos_recentes", "voos_lugar", "mostrar_avioes", "esconder_avioes", "localizar_voo", "tocar_radio", "parar_radio", "satelite"}


# ── globo ──

def test_globo_desenha_e_acha_o_pais_clicado():
    import tkinter as tk
    from pidreams.ui.globe import GlobeView
    root = tk.Tk()
    root.geometry("500x500")
    g = GlobeView(root)
    g.pack(fill="both", expand=True)
    root.update()
    g.lon0, g.lat0 = math.radians(139.7), math.radians(35.7)        # Tokyo in the centre
    g.render()
    lat, lon = g.screen_to_latlon(g.canvas.winfo_width() / 2, g.canvas.winfo_height() / 2)
    assert abs(lat - 35.7) < 0.5 and abs(lon - 139.7) < 0.5
    assert world.country_at(lat, lon)["name"] == "Japão"
    root.destroy()


def test_loop_nao_sobrescreve_nome_de_modulo():
    """A local named `tools` inside run_agent shadowed the tools module and the loop died at start."""
    import ast
    from pathlib import Path
    src = Path("pidreams/agent/loop.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_agent")
    local = {t.id for n in ast.walk(fn) for t in getattr(n, "targets", []) if isinstance(t, ast.Name)}
    modules = {a.asname or a.name.split(".")[0] for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not local & modules
