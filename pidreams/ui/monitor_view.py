"""The Monitoramento screen: the globe, its layers and filters, the details of a clicked point,
the radio playing and the data credits. Data loads in the background; a source that fails only
shows its own notice."""

import datetime
import logging
import threading
import time
import tkinter as tk
from tkinter import ttk

from pidreams.monitor import planes
from pidreams.monitor import satellites as sat_mod
from pidreams.monitor import sources
from pidreams.ui import theme
from pidreams.ui.globe import GlobeView

CREDITS = ("Dados: Natural Earth · CelesTrak · USGS · Open-Meteo.com · GeoNames · adsb.lol (ODbL) · Radio Browser · "
           "Notícias: Agência Brasil · BBC News Brasil · DW · ONU News · RTP · GDELT (gdeltproject.org)")
_FILTERS = {"Todos": None, **{label: {kind} for kind, label in sat_mod.TYPES.items()}}
log = logging.getLogger(__name__)

PLANES_EVERY_S = 10          # told to the source's maintainer; change here if they ask for another rate
_PLANES_RETRY_S = (60, 60, 300)   # waits after the 1st, 2nd and 3rd+ failure in a row: never insist
_PLANES_ZOOM = 12.0          # a place asked or clicked with the layer on is shown this close


class MonitorView(tk.Frame):
    def __init__(self, parent, on_close, on_ask, radio):
        """on_ask(text): a question for the monitor's agent (a country was clicked)."""
        super().__init__(parent, bg=theme.BG)
        self._on_close, self._on_ask, self._radio = on_close, on_ask, radio
        self.satellites = None
        self._loaded = False

        bar = tk.Frame(self, bg=theme.GLASS)
        bar.pack(fill=tk.X)
        tk.Label(bar, text=f"{theme.ICON['globe']}  Monitoramento", bg=theme.GLASS, fg=theme.TEXT,
                 font=theme.FONT_SECTION).pack(side=tk.LEFT, padx=theme.px(12), pady=theme.px(8))
        theme.button(bar, "Fechar", on_close, icon="close", font=theme.FONT_SMALL).pack(side=tk.RIGHT, padx=theme.px(8))
        self._layer_vars = {}
        for key, text in (("satellites", "Satélites"), ("quakes", "Terremotos"), ("radios", "Rádios"),
                          ("planes", "Aviões")):
            var = tk.BooleanVar(value=key not in ("radios", "planes"))
            self._layer_vars[key] = var
            theme.check(bar, text, var, command=self._apply_layers).pack(side=tk.LEFT, padx=theme.px(3))
        # The satellite filter goes in the footer: in the top bar it was squeezed to "Todı".
        self._filter = tk.StringVar(value="Todos")
        self._filter.trace_add("write", lambda *_: self._apply_layers())

        self.globe = GlobeView(self, on_pick=self._picked)
        self.globe.pack(fill=tk.BOTH, expand=True)
        self.tracker = planes.Tracker()
        self.globe.tracker = self.tracker
        self._region = None              # (lat, lon) of the planes being shown
        self._planes_job = None
        self._planes_busy = False
        self._planes_next = 0.0          # monotonic time of the next query allowed
        self._planes_failures = 0
        self._pending_plane = None       # hex of a flight looked up by the agent, selected when it arrives
        self._planes_note = tk.StringVar(value="")

        self._status = tk.StringVar(value="Carregando satélites, terremotos e rádios…")
        foot = tk.Frame(self, bg=theme.GLASS)
        foot.pack(fill=tk.X)
        row = tk.Frame(foot, bg=theme.GLASS)
        row.pack(fill=tk.X, padx=theme.px(12), pady=(theme.px(4), 0))
        tk.Label(row, text="Satélites:", bg=theme.GLASS, fg=theme.TEXT2, font=theme.FONT_SMALL).pack(side=tk.LEFT)
        ttk.Combobox(row, textvariable=self._filter, values=list(_FILTERS), state="readonly", width=18
                     ).pack(side=tk.LEFT, padx=(theme.px(6), theme.px(12)))
        tk.Label(row, textvariable=self._planes_note, bg=theme.GLASS, fg=theme.PEACH, font=theme.FONT_SMALL
                 ).pack(side=tk.RIGHT)
        tk.Label(row, textvariable=self._status, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                 anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        credits = tk.Label(foot, text=CREDITS, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                           anchor="w", justify="left")
        credits.pack(fill=tk.X, padx=theme.px(12), pady=(theme.px(2), theme.px(6)))
        foot.bind("<Configure>", lambda e: credits.config(wraplength=max(theme.px(200), e.width - theme.px(24))))

        # Radio playing, over the bottom of the globe.
        self._radio_bar = tk.Frame(self.globe, bg=theme.GLASS_HI, highlightthickness=1, highlightbackground=theme.BORDER)
        self._radio_text = tk.Label(self._radio_bar, text="", bg=theme.GLASS_HI, fg=theme.VIOLET, font=theme.FONT)
        self._radio_text.pack(side=tk.LEFT, padx=theme.px(10), pady=theme.px(6))
        theme.button(self._radio_bar, "Parar", self._radio.stop, font=theme.FONT_SMALL).pack(side=tk.LEFT, padx=theme.px(6))

        # Details of a clicked point, floating at the top left of the globe.
        self._info = tk.Frame(self.globe, bg=theme.GLASS_HI, highlightthickness=1, highlightbackground=theme.BORDER)
        self._info_text = tk.Label(self._info, text="", bg=theme.GLASS_HI, fg=theme.TEXT, font=theme.FONT,
                                   justify="left", anchor="w", wraplength=theme.px(280))
        self._info_text.grid(row=0, column=0, sticky="w", padx=(theme.px(10), 0), pady=theme.px(8))
        tk.Button(self._info, text=theme.ICON["close"], command=self._close_info, bg=theme.GLASS_HI, fg=theme.TEXT2,
                  activebackground=theme.HOVER, relief=tk.FLAT, bd=0, font=theme.FONT, cursor="hand2"
                  ).grid(row=0, column=1, sticky="ne", padx=theme.px(4), pady=theme.px(4))
        self._info_button = theme.button(self._info, "", None, font=theme.FONT_SMALL)

    # ── open / close ──

    def open(self) -> None:
        self.globe.start()
        self._planes_tick()
        if not self._loaded:
            self._loaded = True
            threading.Thread(target=self._load, daemon=True).start()

    def close(self) -> None:
        self.globe.stop()
        if self._planes_job is not None:
            self.after_cancel(self._planes_job)
            self._planes_job = None
        self._set_region(None)
        self._radio.stop()
        self._close_info()

    def _load(self) -> None:
        notes = []
        try:
            sats, age = sat_mod.load()
            self.after(0, lambda: self.globe.set_satellites(sats))
            self.satellites = sats
            old = " (órbitas antigas: posições aproximadas)" if age > sat_mod.STALE_AFTER_S else ""
            hours = age / 3600
            notes.append(f"{len(sats):,} satélites".replace(",", ".") +
                         (f", órbitas de {hours:.0f} h atrás" if hours >= 1 else "") + old)
        except sources.SourceError as e:
            notes.append(str(e))
        for name, fn, setter in (("terremotos", sources.quakes, self.globe.set_quakes),
                                 ("rádios", sources.radios, self.globe.set_radios)):
            try:
                data = fn()
                self.after(0, lambda d=data, s=setter: s(d))
                notes.append(f"{len(data):,} {name}".replace(",", "."))
            except sources.SourceError as e:
                notes.append(str(e))
        self.after(0, lambda: self._status.set(" · ".join(notes)))

    # ── layers and picks ──

    def _apply_layers(self) -> None:
        for key, var in self._layer_vars.items():
            self.globe.layers[key] = var.get()
        self.globe.sat_kinds = _FILTERS.get(self._filter.get())
        if not self.globe.layers["planes"]:
            self._set_region(None)
            self._planes_note.set("")

    # ── planes ──

    def set_planes(self, on: bool) -> None:
        self._layer_vars["planes"].set(on)
        self._apply_layers()

    def _set_region(self, region) -> None:
        if region != self._region:
            self._region = region
            self.tracker.clear()
            self._planes_next = 0.0
            if self.globe.selected and self.globe.selected[0] == "plane":
                self._close_info()

    def _planes_tick(self) -> None:
        """Once a second while the monitor is open: which region to show and whether to query it.
        Nothing is queried with the layer off, the monitor closed or no region (FR-003)."""
        self._planes_job = self.after(1000, self._planes_tick)
        if not self.globe.layers["planes"]:
            return
        lat, lon = self.globe.center()
        region = planes.region_for(lat, lon, self.globe.zoom, self._region, self.globe.settled_s())
        self._set_region(region)
        if region is None:
            self._planes_note.set("Aviões: aproxime o globo ou escolha um lugar.")
            return
        if self._planes_busy or time.monotonic() < self._planes_next:
            return
        self._planes_busy = True
        if not len(self.tracker):
            self._planes_note.set("Aviões: buscando…")
        threading.Thread(target=self._fetch_planes, args=(region,), daemon=True).start()

    def _fetch_planes(self, region) -> None:
        try:
            data, error = sources.aircraft(*region), None
            log.info(f"[Monitor] planes: {len(data)} around {region[0]:.2f},{region[1]:.2f}")
        except sources.SourceError as e:
            data, error = None, str(e)
            log.warning(f"[Monitor] planes around {region[0]:.2f},{region[1]:.2f}: {e.__cause__ or e}")
        try:
            self.after(0, self._planes_arrived, region, data, error)
        except (RuntimeError, tk.TclError):
            pass                             # window closed meanwhile

    def _planes_arrived(self, region, data, error) -> None:
        self._planes_busy = False
        if region != self._region or not self.globe.layers["planes"]:
            return                           # the view moved on or the layer was turned off
        if error:
            wait = _PLANES_RETRY_S[min(self._planes_failures, len(_PLANES_RETRY_S) - 1)]
            self._planes_failures += 1
            self._planes_next = time.monotonic() + wait
            self._planes_note.set(f"Aviões: {error.rstrip('.')}; tento de novo em "
                                  f"{'1 minuto' if wait == 60 else '5 minutos'}.")
            return
        self._planes_failures = 0
        self._planes_next = time.monotonic() + PLANES_EVERY_S
        self.tracker.update(data, time.monotonic())
        n = len(self.tracker)                # the planes drawn: a position older than 60 s is not
        i = self.tracker.index(self._pending_plane) if self._pending_plane else None
        if i is not None:
            self._pending_plane = None
            self.globe.selected = ("plane", self.tracker.hexes[i])
            self._picked("plane", i)
        self._planes_note.set("Aviões: nenhum voando nesta região agora." if not n else
                              f"Aviões: {n} nesta região")
        self._refresh_plane_info()

    def _refresh_plane_info(self) -> None:
        """The details box follows the selected plane's new data, and closes when it is gone."""
        if not self.globe.selected or self.globe.selected[0] != "plane":
            return
        i = self.tracker.index(self.globe.selected[1])
        if i is None:
            self._close_info()
            self._planes_note.set("Aviões: o avião selecionado saiu da região ou parou de ser visto.")
            return
        self._info_text.config(text=plane_text(self.tracker.get(i)))

    def _picked(self, kind: str, data) -> None:
        if kind == "country":
            self._close_info()
            if data.get("name"):
                self._on_ask(f"Quais as notícias de hoje sobre: {data['name']}?")
            return
        button = None
        if kind == "satellite" and self.satellites is not None:
            lat, lon, alt, _ok = self.satellites.positions()
            text = (f"{self.satellites.names[data]}\n{sat_mod.TYPES[self.satellites.kinds[data]]} · "
                    f"{self.satellites.owners[data]} · {alt[data]:.0f} km de altitude")
        elif kind == "radio":
            station = self.globe.radios[data]
            text = f"{station['name']}\nRádio · {station['country']}"
            button = ("Tocar", lambda: self._radio.play(station))
        elif kind == "plane":
            text = plane_text(self.tracker.get(data))
        elif kind == "quake":
            q = self.globe.quakes[data]
            when = datetime.datetime.fromtimestamp(q["time"]).strftime("%d/%m %H:%M")
            text = f"Terremoto de magnitude {q['mag']:.1f}\n{q['place']} · {q['depth']:.0f} km de profundidade · {when}"
        else:
            return
        self._info_text.config(text=text)
        if button:
            self._info_button.config(text=button[0], command=button[1])
            self._info_button.grid(row=1, column=0, columnspan=2, sticky="e", padx=theme.px(10), pady=(0, theme.px(8)))
        else:
            self._info_button.grid_remove()
        self._info.place(x=theme.px(12), y=theme.px(12))
        self._info.lift()

    def selected_flight(self) -> str | None:
        """Flight number of the plane selected on the globe (read by the agent's thread), or None."""
        selected = self.globe.selected
        if not selected or selected[0] != "plane":
            return None
        i = self.tracker.index(selected[1])
        return (self.tracker.get(i).get("callsign") or None) if i is not None else None

    def _close_info(self) -> None:
        self._info.place_forget()
        self.globe.selected = None

    def focus(self, data: dict) -> None:
        self.globe.focus(data["lat"], data["lon"])
        if "plane" in data:
            self._pending_plane = data["plane"]
        if self.globe.layers["planes"] and self.globe.zoom < _PLANES_ZOOM:
            self.globe.zoom_to(_PLANES_ZOOM)
        if "satellite" in data:
            self.globe.selected = ("satellite", data["satellite"])

    def radio_changed(self, station: dict | None, error: str | None) -> None:
        if station:
            self._radio_text.config(text=f"♪  {station['name']} · {station['country']}")
            self._radio_bar.place(relx=0.5, rely=1.0, y=-theme.px(12), anchor="s")
            self._radio_bar.lift()
        else:
            self._radio_bar.place_forget()
        if error:
            self._status.set(error)


def plane_text(a: dict) -> str:
    """Details box of a plane; missing fields are left out."""
    title = a.get("callsign") or "Voo não informado"
    lines = [title, " · ".join(x for x in (a.get("type"), a.get("reg")) if x)]
    facts = []
    if a.get("alt_ft") is not None:
        facts.append(f"{a['alt_ft']:,.0f} pés ({a['alt_ft'] * 0.3048:,.0f} m)".replace(",", "."))
    if a.get("speed_kt"):
        facts.append(f"{a['speed_kt'] * 1.852:,.0f} km/h".replace(",", "."))
    if a.get("track") is not None:
        facts.append(f"rumo {a['track']:.0f}°")
    lines.append(" · ".join(facts))
    return "\n".join(line for line in lines if line)
