"""Aviões em tempo real: leitura da fonte (resposta gravada fictícia), estimativa, correção suave,
rastros e regras da região. Relógio controlado, sem rede."""

from pathlib import Path

import numpy as np
import pytest

from pidreams.monitor import planes, sources

RAW = (Path(__file__).parent / "data" / "adsb_point.json").read_bytes()


def test_fonte_tira_solo_e_sem_posicao():
    ac = sources.parse_aircraft(RAW)
    assert [a["hex"] for a in ac] == ["e4a001", "e4a002", "e4a003", "e4a006", "e4a007"]   # 004 no solo, 005 sem posição
    first = ac[0]
    assert first["callsign"] == "EXM1001" and first["reg"] == "PR-XEA" and first["type"] == "A320"
    assert first["alt_ft"] == 35000 and first["speed_kt"] == 480.0 and first["track"] == 90.0
    assert ac[2]["callsign"] == ""                     # sem indicativo: a tela diz "voo não informado"


def test_aviao_avanca_pela_velocidade_e_rumo():
    t = planes.Tracker()
    t.update([{"hex": "a", "lat": 0.0, "lon": 0.0, "speed_kt": 480, "track": 90, "fix_age_s": 0}], now=100.0)
    lat, lon, _ = t.positions(110.0)
    km = planes.distance_km(0.0, 0.0, lat[0], lon[0])
    assert km == pytest.approx(480 * 1.852 / 3600 * 10, rel=0.01)       # ~2,5 km em 10 s
    assert lon[0] > 0 and abs(lat[0]) < 1e-6                            # para leste


def test_posicao_velha_e_descontada():
    t = planes.Tracker()
    t.update([{"hex": "a", "lat": 0.0, "lon": 0.0, "speed_kt": 480, "track": 0, "fix_age_s": 5}], now=100.0)
    lat, _lon, _ = t.positions(100.0)
    assert planes.distance_km(0.0, 0.0, lat[0], 0.0) == pytest.approx(480 * 1.852 / 3600 * 5, rel=0.01)


def test_dado_novo_corrige_sem_salto():
    t = planes.Tracker()
    t.update([{"hex": "a", "lat": 0.0, "lon": 0.0, "speed_kt": 0, "track": 90, "fix_age_s": 0}], now=0.0)
    before = t.positions(10.0)
    t.update([{"hex": "a", "lat": 0.0, "lon": 0.05, "speed_kt": 0, "track": 90, "fix_age_s": 0}], now=10.0)
    same_frame = t.positions(10.0)
    assert same_frame[1][0] == pytest.approx(before[1][0], abs=1e-9)     # no frame of the update: no jump
    halfway = t.positions(11.0)[1][0]
    assert 0.0 < halfway < 0.05                                          # on the way
    assert t.positions(12.5)[1][0] == pytest.approx(0.05)                # arrived after ~2 s


def test_aviao_some_depois_de_60s_sem_posicao():
    t = planes.Tracker()
    t.update([{"hex": "a", "lat": 0, "lon": 0, "speed_kt": 0, "track": 0, "fix_age_s": 0},
              {"hex": "b", "lat": 1, "lon": 1, "speed_kt": 0, "track": 0, "fix_age_s": 0}], now=0.0)
    t.update([{"hex": "b", "lat": 1, "lon": 1, "speed_kt": 0, "track": 0, "fix_age_s": 0}], now=30.0)
    assert len(t) == 2                                                    # 'a' still within 60 s
    t.update([{"hex": "b", "lat": 1, "lon": 1, "speed_kt": 0, "track": 0, "fix_age_s": 0}], now=61.0)
    assert t.hexes == ["b"]
    t.update([{"hex": "c", "lat": 2, "lon": 2, "speed_kt": 0, "track": 0, "fix_age_s": 75}], now=62.0)
    assert "c" not in t.hexes                                             # already too old when it arrived


def test_rastro_cresce_com_limite_e_some_com_o_aviao():
    t = planes.Tracker()
    t.update([{"hex": "a", "lat": 0, "lon": 0, "speed_kt": 480, "track": 0, "fix_age_s": 0}], now=0.0)
    for k in range(200):
        t.positions(k * planes.TRAIL_EVERY_S)
    lat, _lon, age = t.trails()
    assert len(lat) == planes.TRAIL_MAX and age.min() == 0 and np.all(np.diff(lat) > 0)   # newest last, heading north
    t.update([], now=planes.STALE_S + 1)
    assert len(t.trails()[0]) == 0


@pytest.mark.parametrize("zoom,current,settled,expected", [
    (3.0, None, 9.0, None),                    # afastado demais
    (8.0, None, 0.5, None),                    # ainda se mexendo
    (8.0, None, 2.0, (-23.5, -46.6)),          # assentou: região nova
    (8.0, (-23.6, -46.7), 2.0, (-23.6, -46.7)),  # menos de 100 km: mantém
    (8.0, (-20.0, -46.6), 0.5, (-20.0, -46.6)),  # longe, mas ainda girando: mantém
    (8.0, (-20.0, -46.6), 2.0, (-23.5, -46.6)),  # longe e assentado: muda
])
def test_regiao(zoom, current, settled, expected):
    assert planes.region_for(-23.5, -46.6, zoom, current, settled) == expected


# ── camada na tela (Tk, fonte falsa) ──

class _Radio:
    def stop(self):
        pass


@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk
    from pidreams.ui import theme
    root = tk.Tk()                     # one window for the module: creating many in a row sometimes fails to read init.tcl
    root.withdraw()
    theme.init(root)
    yield root
    root.destroy()


@pytest.fixture
def view(monkeypatch, tk_root):
    from pidreams.ui.monitor_view import MonitorView
    v = MonitorView(tk_root, on_close=lambda: None, on_ask=lambda _t: None, radio=_Radio())
    calls = []
    monkeypatch.setattr(sources, "aircraft", lambda lat, lon: calls.append((lat, lon)) or sources.parse_aircraft(RAW))
    # Synchronous threads (the planes fetch, the globe's outline): a real one would race with the test.
    monkeypatch.setattr("pidreams.ui.monitor_view.threading.Thread",
                        lambda target, args=(), daemon=False: type("T", (), {"start": lambda self: target(*args),
                                                                             "join": lambda self, timeout=None: None})())
    monkeypatch.setattr(v, "after", lambda ms, fn=None, *a: fn(*a) if ms == 0 and fn else "job")
    v.calls = calls
    yield v
    v.destroy()


def _settle(view, zoom=8.0, lat=-23.5, lon=-46.6):
    import math
    view.globe.zoom, view.globe.lat0, view.globe.lon0 = zoom, math.radians(lat), math.radians(lon)
    view.globe._moved_at -= 10                     # the view has been still for a while


def test_camada_desligada_nao_consulta(view):
    _settle(view)
    view._planes_tick()
    assert view.calls == [] and len(view.tracker) == 0


def test_sem_regiao_pede_para_aproximar(view):
    view.set_planes(True)
    _settle(view, zoom=2.0)
    view._planes_tick()
    assert view.calls == [] and "aproxime" in view._planes_note.get()


def test_regiao_assentada_consulta_e_mostra_a_contagem(view):
    view.set_planes(True)
    _settle(view)
    view._planes_tick()
    assert len(view.calls) == 1 and len(view.tracker) == 4          # e4a006: position 75 s old
    assert view._planes_note.get() == "Aviões: 4 nesta região"
    view._planes_tick()                            # within 10 s: no second query
    assert len(view.calls) == 1


def test_desligar_e_fechar_param_e_limpam(view):
    view.set_planes(True)
    _settle(view)
    view._planes_tick()
    view.set_planes(False)
    assert len(view.tracker) == 0 and view._planes_note.get() == ""
    view._planes_tick()
    assert len(view.calls) == 1
    view.set_planes(True)
    view.close()
    assert view._region is None and len(view.tracker) == 0


def test_falha_da_fonte_avisa_e_espera(view, monkeypatch):
    def fail(lat, lon):
        raise sources.SourceError("Não consegui os aviões agora (sem conexão ou a fonte não respondeu).")
    monkeypatch.setattr(sources, "aircraft", fail)
    view.set_planes(True)
    _settle(view)
    view._planes_tick()
    assert "tento de novo em 1 minuto" in view._planes_note.get()
    import time
    assert view._planes_next - time.monotonic() > 50


def test_clique_acha_o_aviao_certo_entre_vizinhos(view):
    view.set_planes(True)
    _settle(view, zoom=12.0)
    view.tracker.update([
        {"hex": "perto", "callsign": "EXM1", "lat": -23.50, "lon": -46.60, "speed_kt": 0, "track": 0, "fix_age_s": 0},
        {"hex": "vizinho", "callsign": "EXM2", "lat": -23.50, "lon": -46.30, "speed_kt": 0, "track": 0, "fix_age_s": 0},
    ], now=__import__("time").monotonic())
    g = view.globe
    g.surface.config(width=600, height=600)
    g.surface.winfo_width = lambda: 600
    g.surface.winfo_height = lambda: 600
    g.render()
    sx, sy, vis = g._screen["plane"]
    assert vis.all() and abs(sx[1] - sx[0]) > 7                          # far enough apart to click each
    picked = []
    g.on_pick = lambda kind, i: picked.append((kind, i))
    g._press(type("E", (), {"x": int(sx[1]), "y": int(sy[1])}))
    g._release(type("E", (), {"x": int(sx[1]), "y": int(sy[1])}))
    assert picked == [("plane", 1)] and g.selected == ("plane", "vizinho")


def test_quadro_sem_dados_opcionais():
    from pidreams.ui.monitor_view import plane_text
    assert plane_text({"callsign": "EXM1001", "type": "A320", "reg": "PR-XEA", "alt_ft": 35000, "speed_kt": 480,
                       "track": 90}) == "EXM1001\nA320 · PR-XEA\n35.000 pés (10.668 m) · 889 km/h · rumo 90°"
    assert plane_text({"callsign": "", "type": "", "reg": "", "alt_ft": None, "speed_kt": None, "track": None}) \
        == "Voo não informado"


# ── agente ──

def test_mostrar_e_esconder_avioes_pelo_agente(monkeypatch):
    from pidreams.monitor import agent
    monkeypatch.setattr(sources, "place", lambda name: {"name": "Cidade Exemplo", "country": "", "lat": -23.5, "lon": -46.6})
    monkeypatch.setattr(sources, "aircraft", lambda lat, lon: sources.parse_aircraft(RAW))
    events = []
    tools = agent.MonitorAgentTools(lambda e, d: events.append((e, d)))
    reply = tools.dispatch("mostrar_avioes", {"lugar": "Cidade Exemplo"})
    assert [e for e, _ in events] == ["monitor_planes", "monitor_focus"]          # layer on before the focus
    assert events[0][1] == {"on": True} and "5 aviões" in reply and "Cidade Exemplo" in reply
    events.clear()
    assert "tirei" in tools.dispatch("esconder_avioes", {})
    assert events == [("monitor_planes", {"on": False})]


def test_evento_do_agente_liga_a_camada_e_aproxima(view):
    view.globe.zoom = 2.0
    view.set_planes(True)
    view.focus({"lat": 51.47, "lon": -0.45, "name": "Londres"})
    assert view._layer_vars["planes"].get() and view.globe.zoom == 12.0
    view.set_planes(False)
    assert not view.globe.layers["planes"]


def test_contorno_detalhado_carrega_em_segundo_plano(view):
    """It took 809 ms the first time, in the middle of a zoom: now it loads when the globe starts,
    and until then the zoom uses the coarse outline instead of waiting."""
    from pidreams.monitor import world
    outline = world.outline()
    assert outline.shape[1] == 2 and len(outline) > 100_000
    g = view.globe
    g.surface.winfo_width = lambda: 400
    g.surface.winfo_height = lambda: 400
    g.zoom = 8.0
    g.render()                                      # not loaded yet: draws, with the coarse outline
    g.start()
    g._outline_thread.join(10)
    g.stop()
    assert g._outline is not None and len(g._outline) == len(outline)
    g.render()


def test_localizar_voo_pelo_numero(monkeypatch):
    from pidreams.monitor import agent
    asked = []

    def fake_get(url, timeout=15):
        asked.append(url)
        return RAW if "EXM1001" in url else b'{"ac": []}'
    monkeypatch.setattr(sources, "_get", fake_get)
    events = []
    tools = agent.MonitorAgentTools(lambda e, d: events.append((e, d)))
    reply = tools.dispatch("localizar_voo", {"voo": "exm 1001"})
    assert asked[0].endswith("/v2/callsign/EXM1001")                     # spaces out, upper case
    assert "EXM1001" in reply and "A320 · PR-XEA" in reply and "10.668 m" in reply and "Brasil" in reply
    assert events[0] == ("monitor_planes", {"on": True})
    assert events[1][0] == "monitor_focus" and events[1][1]["plane"] == "e4a001"
    assert "Não encontrei o voo XXX9999" in tools.dispatch("localizar_voo", {"voo": "XXX9999"})


def test_voo_localizado_fica_selecionado_quando_chega(view):
    view.set_planes(True)
    view.focus({"lat": -23.5, "lon": -46.6, "name": "EXM2002", "plane": "e4a002"})
    _settle(view, zoom=12.0)
    view._planes_tick()
    assert view.globe.selected == ("plane", "e4a002") and "EXM2002" in view._info_text.cget("text")


def test_comandos_curtos_vao_direto_para_a_ferramenta():
    from pidreams.monitor import agent
    assert agent.direct_command("Para a rádio.") == "parar_radio"
    assert agent.direct_command("Some com os aviões do globo!") == "esconder_avioes"
    assert agent.direct_command("Esconde os aviões") == "esconder_avioes"
    assert agent.direct_command("Para a rádio da França e toca outra") is None       # longer requests go to the model
    assert agent.direct_command("mostra os aviões sobre Londres") is None


def test_esse_voo_vira_o_numero_do_aviao_selecionado():
    from pidreams.monitor.agent import name_selected_plane as name
    assert name("Onde tá esse voo?", "EXM1001") == "Onde tá o voo EXM1001?"
    assert name("Qual a altitude desse avião?", "EXM1001") == "Qual a altitude do voo EXM1001?"
    assert name("De onde é essa aeronave?", "EXM1001") == "De onde é o voo EXM1001?"
    assert name("professe voo", "EXM1001") == "professe voo"                     # whole words only
    assert name("Onde tá esse voo?", None) == "Onde tá esse voo?"                 # nothing selected


def test_tela_informa_o_voo_selecionado(view):
    view.set_planes(True)
    _settle(view)
    view._planes_tick()
    assert view.selected_flight() is None
    view.globe.selected = ("plane", "e4a001")
    assert view.selected_flight() == "EXM1001"
    view.globe.selected = ("plane", "e4a003")                                     # no flight number
    assert view.selected_flight() is None


def test_animacao_de_entrada_termina_no_globo_inteiro(view):
    from pidreams.ui import globe as globe_mod
    g = view.globe
    g.intro()
    t0 = g._intro_t0
    g._step_intro(t0, 0.033)
    assert g.zoom == pytest.approx(globe_mod._INTRO_ZOOM) and g._fade < 0.5        # starts close and dark
    g._step_intro(t0 + globe_mod._INTRO_S / 2, 0.033)
    assert 1.0 < g.zoom < globe_mod._INTRO_ZOOM
    g._step_intro(t0 + globe_mod._INTRO_S + 0.01, 0.033)
    assert (g.zoom, g._fade, g._intro_t0) == (1.0, 1.0, None)                       # the whole globe, full light


def test_fundo_por_tabela_igual_ao_calculo_direto(view):
    """The lookup table replaced computing the sphere for every pixel on every zoom step."""
    import numpy as np
    from pidreams.ui import globe as globe_mod
    g = view.globe
    w, h, radius, cx, cy = 200, 150, 60.0, 100.0, 75.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius
    img = np.empty((h, w, 3), np.float32)
    img[:] = globe_mod._BG
    inside = d < 1
    img[inside] = globe_mod._SPHERE * (0.55 + 0.45 * np.sqrt(1 - d[inside] ** 2))[:, None] + globe_mod._BG * 0.2
    glow = np.clip(1 - np.abs(d - 1) * 14, 0, 1) * 0.55 + np.clip(1 - (d - 1) * 3, 0, 1) * (d > 1) * 0.12
    img += glow[..., None] * globe_mod._LAND * 0.45
    direct = np.clip(img, 0, 255).astype(np.int16)
    looked_up = g._background(w, h, radius, cx, cy).astype(np.int16)
    diff = np.abs(looked_up - direct).max(axis=2)
    # Equal everywhere but on the sphere's very edge, where one pixel can fall on either side.
    assert diff.mean() < 0.2
    assert (np.abs(d[diff > 4] - 1) < 1.5 / radius).all()


def test_rodinha_desliza_ate_o_zoom_e_encerra_a_abertura(view):
    """The wheel sets a goal the frames glide to; using it during the opening ends the animation
    with the points at full light."""
    from types import SimpleNamespace
    g = view.globe
    g.intro()
    g.zoom, g._fade = 1.0, 0.3                     # partway through the opening
    g._wheel(SimpleNamespace(delta=120))
    assert g._intro_t0 is None and g._fade == 1.0
    assert g.zoom == 1.0 and g._zoom_goal == pytest.approx(1.12)          # not yet: the frames take it there
    g.surface.winfo_ismapped = lambda: True
    g.render = lambda: None
    for _ in range(40):
        g._last_tick = __import__("time").monotonic() - 0.033
        g._tick()
    assert g._zoom_goal is None and g.zoom == pytest.approx(1.12)


def test_sem_opengl_o_globo_desenha_com_gdi(view, monkeypatch):
    """A remote session or an old driver: the painter fails to start and GDI draws the same frame."""
    from pidreams.ui import globe_gl

    def no_gl(*_a, **_k):
        raise globe_gl.GLUnavailable("sem OpenGL neste teste")
    monkeypatch.setattr(globe_gl, "GlobePainter", no_gl)
    g = view.globe
    g._painters.clear()
    g.surface.winfo_width = lambda: 400
    g.surface.winfo_height = lambda: 300
    g.render()
    assert g._painters[g.surface.winfo_id()] is None and g._gdi.size == (400, 300)
    assert g._gdi.pixels[150, 200, :3].any()                    # the sphere was painted
