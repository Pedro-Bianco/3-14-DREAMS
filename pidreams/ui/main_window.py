"""Janela principal do PI dreams."""

import logging
import tkinter as tk
from tkinter import ttk
import os
import threading
import time
import asyncio
import ctypes
import ctypes.wintypes
import queue
import datetime
import webbrowser
from pidreams import pc
from pidreams.agent import problems
from pidreams.agent.loop import run_agent
from pidreams.audio import devices
from pidreams.audio.claps import ClapListener
from pidreams.audio import tts as tts_audio
from pidreams.core import paths
from pidreams.core.config import CONFIG
from pidreams.core.settings import SETTINGS
from pidreams.core.text import date_in_words, remove_emojis
from pidreams.memory.store import LTMStore
from pidreams.memory.kb_store import KBStore
from pidreams.plugins.manager import ServiceManager
from pidreams.mcp import confirmation
from pidreams.mcp.connections import Connections
from pidreams.pc.games import game_running
from pidreams.ui import appearances, theme
from pidreams.ui.tray import TrayIcon
from pidreams.ui.widgets import SystemMonitor, WeatherFetcher, MeterWidget
from pidreams.ui.camera_window import CameraWindowMixin
from pidreams.ui.notice_bar import NoticeBar
from pidreams.ui.today_panel import TodayPanel
from pidreams.ui.panels.apps import AppsPanelMixin
from pidreams.ui.panels.audio import AudioPanelMixin
from pidreams.ui.panels.connections import ConnectionsPanelMixin
from pidreams.ui.panels.kb import KBPanelMixin
from pidreams.ui.panels.memory import MemoryPanelMixin
from pidreams.ui.panels.services import ServicesPanelMixin
from pidreams.audio import tts as tts_module
from pidreams.monitor.agent import MonitorAgentTools
from pidreams.monitor.radio import RadioPlayer
from pidreams.ui.monitor_view import MonitorView
from pidreams.research.agent import ResearchAgentTools
from pidreams.ui.research_view import ResearchView

log = logging.getLogger(__name__)

# Also used to find the window when a second instance is opened.
WINDOW_TITLE = "PI dreams"

_TRAY_TICK_MS = 5000          # microphone retry while asleep; idle check while awake
_GAMES_CHECK_S = 3.0


def _unload_quietly():
    from pidreams.agent.llm import unload_model

    try:
        unload_model()
    except Exception as e:
        log.warning("unload before closing: %r", e)

# ─────────────────────────────────────────────────────────────────────────────
#  Main Application
# ─────────────────────────────────────────────────────────────────────────────

class AgentApp(ServicesPanelMixin, MemoryPanelMixin, KBPanelMixin,
               AppsPanelMixin, AudioPanelMixin, CameraWindowMixin, ConnectionsPanelMixin):
    _DEFAULT_APPS = [
        ("notepad",    "Notepad",      True),
        ("calc",       "Calculadora",  True),
        ("mspaint",    "Paint",        True),
        ("explorer",   "Explorador",   True),
        ("chrome",     "Chrome",       True),
        ("firefox",    "Firefox",      True),
        ("code",       "VS Code",      True),
        ("spotify",    "Spotify",      True),
        ("discord",    "Discord",      True),
        ("vlc",        "VLC",          True),
        ("winword",    "Word",         True),
        ("excel",      "Excel",        True),
        ("outlook",    "Outlook",      True),
        ("obs64",      "OBS Studio",   True),
        ("steam",      "Steam",        True),
        ("taskmgr",    "Ger. Tarefas", False),
        ("cmd",        "Cmd",          False),
        ("powershell", "PowerShell",   False),
    ]

    def __init__(self, start_asleep: bool = False):
        self.root = tk.Tk()
        if start_asleep:                 # started with Windows: straight to the tray, no flash
            self.root.withdraw()
        self._start_asleep = start_asleep
        theme.init(self.root)
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg=theme.GLASS)
        self.root.resizable(True, True)
        self.root.minsize(theme.px(theme.MIN_WINDOW[0]), theme.px(theme.MIN_WINDOW[1]))
        self._place_window()
        self._pending: dict[str, str] = {}      # debounced callbacks: key → after id

        self._queue:       queue.Queue = queue.Queue()
        self._loop:        asyncio.AbstractEventLoop | None = None
        self._stop_event:  asyncio.Event | None = None
        self._mode_ref:    list[str] = ["voice"]
        self._mute_ref:    list      = [False]
        # Tray: asleep = no window, conversation model off the GPU, microphone only for two claps.
        self._sleep_ref:   list      = [start_asleep]
        self._tray:        TrayIcon | None     = None
        self._claps:       ClapListener | None = None
        self._last_use = time.monotonic()
        self._quitting = False
        self._text_input:  queue.Queue = queue.Queue()

        self._sphere = None   # center-panel appearance (pidreams/ui/appearances)
        self._appearance_size = 300
        self._appearance_state = "idle"
        # MCP connections: notices and changes come back through the window's event queue.
        self._connections = Connections(on_notice=lambda p: self._emit("problem", p),
                                  on_resolve=lambda c: self._emit("resolved", c),
                                  on_change=lambda id_: self._emit("mcp_changed", id_))
        self._agent_buf:  str = ""

        self._mic_device_ref: list = [devices.index(SETTINGS.get("audio.input_device"), "input")]
        self._out_device_ref: list = [devices.index(SETTINGS.get("audio.output_device"), "output")]
        self._volume_ref:     list = [SETTINGS.get("audio.volume")]

        # Monitoramento: the radio goes quiet while the assistant works or speaks.
        self._agent_working = False
        self._radio = RadioPlayer(self._out_device_ref, self._volume_ref, self._mute_ref,
                                  quiet=lambda: self._agent_working or bool(tts_module.SPEAKING_TEXT[0]),
                                  on_change=lambda s, e: self.root.after(0, self._monitor_view.radio_changed, s, e))
        self._monitor_ref = {"on": False, "fresh": False, "tools": MonitorAgentTools(
            self._emit, radio=self._radio, satellites=lambda: self._monitor_view.satellites,
            selected_flight=lambda: self._monitor_view.selected_flight())}
        self._research_ref = {"on": False, "fresh": False,
                              "tools": ResearchAgentTools(self._emit, kb_store=lambda: self._kb_store)}

        self._input_device_map:  dict[str, int | None] = {}
        self._output_device_map: dict[str, int | None] = {}

        # Background services
        self._sys_monitor   = SystemMonitor()
        self._weather       = WeatherFetcher()

        # Apps permission control
        self._apps_config        = self._load_apps_config()
        self._app_vars:          dict[str, tk.BooleanVar] = {}
        self._apps_inner_frame:  tk.Frame | None          = None
        self._apps_enabled_var:  tk.BooleanVar | None     = None
        self._new_app_var:       tk.StringVar | None      = None

        # Stores carregados em background (LTMStore carrega modelo ~5-10s)
        self._ltm_store: LTMStore | None = None
        self._kb_store:  KBStore  | None = None
        self._stores_ready = threading.Event()

        # Services that can be turned on and off (memory, camera)
        self._services       = ServiceManager(on_log=self._on_service_log)
        self._svc_rows:      dict[str, dict] = {}
        self._svc_log:       tk.Text | None  = None
        self._svc_visible:   bool            = False
        self._svc_signature: tuple          = ()

        self._mem_status_var:    tk.StringVar | None = None
        self._mem_count_var:     tk.StringVar | None = None
        self._mem_list:          tk.Text | None      = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._apply_allowed_apps(self._apps_config)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.configure(bg=theme.BG)
        self.root.grid_rowconfigure(3, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self._build_header()
        line = tk.Canvas(self.root, width=1, height=2, bg=theme.BG, highlightthickness=0)
        line.grid(row=1, column=0, sticky="ew")
        line.bind("<Configure>", lambda e: theme.gradient(line, e.width, 2))

        # Notice bar: shows up only when there is a problem with an action.
        self._notices = NoticeBar(self.root, self._run_action)
        self._notices.grid(row=2, column=0, sticky="ew")
        self._notices.grid_remove()
        self._warn_missing_devices()

        # ── Main 3-column area: glass panels over the background ───────────
        gap = theme.px(theme.GAP)
        main = tk.Frame(self.root, bg=theme.BG)
        main.grid(row=3, column=0, sticky="nsew", padx=gap, pady=gap)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)      # center takes what the side columns leave
        main.bind("<Configure>", lambda e: self._debounce("columns", 100, self._fit_columns, main, e.width))

        # Side panels keep the width the layout gives them: their content must not push it.
        left = self._left_panel = theme.glass(main)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        self._build_left_panel(left)

        center = theme.glass(main)
        center.grid(row=0, column=1, sticky="nsew", padx=gap)
        self._build_center_panel(center)

        right = self._right_panel = theme.glass(main)
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_propagate(False)
        self._build_right_panel(right)

        bottom = tk.Frame(self.root, bg=theme.GLASS, height=theme.px(40),
                          highlightthickness=1, highlightbackground=theme.BORDER)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.grid_propagate(False)
        self._build_bottom_bar(bottom)

        self._set_mode("voice")

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=theme.GLASS, height=theme.px(52))
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="PI dreams", bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_TITLE,
                 padx=theme.px(18)).pack(side=tk.LEFT)

        # Hardware in use. Click = run the detection again.
        self._hw_label = tk.Label(hdr, text="detectando hardware…", bg=theme.GLASS,
                                  fg=theme.MUTED, font=theme.FONT_SMALL, cursor="hand2")
        self._hw_label.pack(side=tk.LEFT)
        self._hw_label.bind("<Button-1>", lambda _e: self._refresh_hardware(redetect=True))
        # Ollama only logs the GPU it uses after starting up: check again later.
        self.root.after(2000, self._refresh_hardware)
        self.root.after(30000, self._refresh_hardware)

        pad = dict(side=tk.RIGHT, pady=theme.px(10))
        theme.button(hdr, "Encerrar", self._on_close, kind="danger", icon="power").pack(padx=(theme.px(8), theme.px(16)), **pad)
        theme.button(hdr, "Configurações", self._open_settings, icon="settings").pack(padx=theme.px(4), **pad)
        self._monitor_button = theme.button(hdr, "Monitoramento", self._toggle_monitor, kind="primary", icon="globe")
        self._monitor_button.pack(padx=theme.px(4), **pad)
        self._research_button = theme.button(hdr, "Pesquisa profunda", self._toggle_research, kind="primary", icon="search")
        self._research_button.pack(padx=theme.px(4), **pad)
        # Saved settings apply right away: audio devices and volume (the prompt,
        # the voice and the weather subscribe on their own).
        SETTINGS.subscribe(lambda st: self.root.after(0, self._apply_settings, st))
        theme.button(hdr, "Dados", lambda: os.startfile(paths.user_data_dir()), icon="folder").pack(padx=theme.px(4), **pad)
        theme.button(hdr, "Log", lambda: os.startfile(paths.logs_dir()), icon="log").pack(padx=theme.px(4), **pad)

        # Assistant state in the middle: colored dot + the agent's own text.
        status = tk.Frame(hdr, bg=theme.GLASS)
        status.place(relx=0.5, rely=0.5, anchor="center")
        size = theme.px(10)
        self._status_dot = tk.Canvas(status, width=size, height=size, bg=theme.GLASS, highlightthickness=0)
        self._status_dot.create_oval(0, 0, size - 1, size - 1, fill=theme.MUTED, width=0, tags="dot")
        self._status_dot.pack(side=tk.LEFT, padx=(0, theme.px(8)))
        self._status_var = tk.StringVar(value="Iniciando…")
        self._status_label = tk.Label(status, textvariable=self._status_var, bg=theme.GLASS,
                                      fg=theme.MUTED, font=theme.FONT_STATUS)
        self._status_label.pack(side=tk.LEFT)

    def _show_status(self, text: str, color: str):
        self._status_var.set(text)
        self._status_label.config(fg=color)
        self._status_dot.itemconfig("dot", fill=color)

    def _refresh_hardware(self, redetect: bool = False):
        def _work():
            from pidreams.hardware import detect, ollama_supervisor

            profile = detect.redetect() if redetect else detect.current_profile()
            usage = ollama_supervisor.backend_in_use()
            if usage:
                profile.ollama_backend, profile.ollama_gpu_name = usage
            detect.save(profile)
            try:
                self.root.after(0, self._show_hardware, profile)
            except (RuntimeError, tk.TclError):
                pass                  # window closed before the detection finished

        threading.Thread(target=_work, daemon=True).start()

    def _show_hardware(self, profile):
        if profile.diverges:
            text, color = f"⚠ {profile.gpu_name} não está sendo usada pelo Ollama", theme.DANGER
        elif profile.backend_detected == "cpu":
            text, color = "CPU — respostas mais lentas", theme.WARN
        else:
            engine = profile.ollama_backend or ("CUDA" if profile.backend_detected == "nvidia" else "Vulkan")
            text, color = f"GPU: {profile.gpu_name} · {engine}", theme.MUTED
        self._hw_label.config(text=text, fg=color)

    # ── Left panel: tabs ──────────────────────────────────────────────────────

    _TABS = (("system", "Sistema"), ("apps", "Apps"), ("memory", "Memória"),
             ("services", "Serviços"), ("kb", "Base"))

    def _build_left_panel(self, parent):
        tab_bar = tk.Frame(parent, bg=theme.GLASS)
        tab_bar.pack(fill=tk.X, padx=theme.px(10), pady=(theme.px(10), 0))
        self._tab_buttons: dict[str, tuple[tk.Label, tk.Canvas]] = {}
        for col, (key, text) in enumerate(self._TABS):
            # Columns share the width: the five names fit the narrowest panel (280 px).
            tab_bar.columnconfigure(col, weight=1)
            cell = tk.Frame(tab_bar, bg=theme.GLASS)
            cell.grid(row=0, column=col)
            lbl = tk.Label(cell, text=text, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_TAB,
                           cursor="hand2", padx=0)
            lbl.pack()
            mark = tk.Canvas(cell, width=1, height=2, bg=theme.GLASS, highlightthickness=0)
            mark.pack(fill=tk.X, pady=(theme.px(4), 0))
            lbl.bind("<Button-1>", lambda _e, k=key: self._switch_left_tab(k))
            lbl.bind("<Enter>", lambda _e, k=key: self._tab_hover(k, True))
            lbl.bind("<Leave>", lambda _e, k=key: self._tab_hover(k, False))
            self._tab_buttons[key] = (lbl, mark)
        tk.Frame(parent, bg=theme.BORDER, height=1).pack(fill=tk.X)

        self._tab_system = tk.Frame(parent, bg=theme.GLASS)
        self._build_system_tab(self._tab_system)

        self._tab_apps = tk.Frame(parent, bg=theme.GLASS)
        self._build_apps_tab(self._tab_apps)

        self._tab_memory = tk.Frame(parent, bg=theme.GLASS)
        self._build_memory_tab(self._tab_memory)

        self._tab_kb = tk.Frame(parent, bg=theme.GLASS)
        self._build_kb_tab(self._tab_kb)

        self._tab_services = tk.Frame(parent, bg=theme.GLASS)
        self._build_services_tab(self._tab_services)

        self._active_tab = "system"
        self._switch_left_tab("system")

    def _tab_hover(self, key: str, inside: bool):
        if key != self._active_tab:
            self._tab_buttons[key][0].config(fg=theme.TEXT2 if inside else theme.MUTED)

    def _switch_left_tab(self, tab: str):
        frames = {"system": self._tab_system, "apps": self._tab_apps, "memory": self._tab_memory,
                  "services": self._tab_services, "kb": self._tab_kb}
        for frame in frames.values():
            frame.pack_forget()
        self._active_tab = tab
        for key, (lbl, mark) in self._tab_buttons.items():
            lbl.config(fg=theme.TEXT if key == tab else theme.MUTED)
            mark.delete("all")
            if key == tab:
                lbl.update_idletasks()
                theme.gradient(mark, lbl.winfo_reqwidth(), 2)
        self._svc_visible = (tab == "services")
        frames[tab].pack(fill=tk.BOTH, expand=True)
        if tab == "services":
            self._refresh_services()

    def _build_system_tab(self, parent):
        # The three cards share the height: no empty half panel on tall windows.
        pad = theme.px(12)
        for attr, label, color in (("_cpu_meter", "CPU", theme.CYAN), ("_ram_meter", "Memória RAM", theme.VIOLET),
                                   ("_gpu_meter", "GPU", theme.PEACH)):
            meter = MeterWidget(parent, label, color)
            meter.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(pad, 0))
            setattr(self, attr, meter)
        tk.Frame(parent, bg=theme.GLASS, height=pad).pack()

    # ── Center panel: appearance + controls ───────────────────────────────────

    def _build_center_panel(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # The appearance follows the free area: recreated at the new size (switching is instant).
        self._appearance_area = tk.Frame(parent, bg=theme.GLASS)
        self._appearance_area.grid(row=0, column=0, sticky="nsew", pady=(theme.px(16), 0))
        self._appearance_frame = tk.Frame(self._appearance_area, bg=theme.GLASS)
        self._appearance_frame.place(relx=0.5, rely=0.5, anchor="center")
        self._switch_appearance(SETTINGS.get("appearance"))
        self._appearance_area.bind("<Configure>", lambda _e: self._debounce("appearance", 100, self._fit_appearance))
        self._today = TodayPanel(self._appearance_area, self._connections)

        # Caption: the sentence being spoken, under the appearance (two lines kept free so
        # the layout does not jump when it appears).
        self._legend = tk.Label(parent, text="", bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_LEGEND,
                                height=2, justify="center")
        self._legend.grid(row=1, column=0, sticky="ew", padx=theme.px(24), pady=(theme.px(4), 0))
        self._legend_hold = 0.0

        # Memory map: what the assistant knows and what it used in the last reply, in view.
        memory_map = tk.Frame(parent, bg=theme.GLASS)
        memory_map.grid(row=2, column=0, sticky="ew", padx=theme.px(16), pady=(theme.px(6), 0))
        self._build_memory_map(memory_map)
        self._memory_map_frame = memory_map

        # Monitoramento takes the place of the appearance and the memory map while open.
        self._monitor_view = MonitorView(parent, on_close=self._close_monitor,
                                         on_ask=lambda q: self._text_input.put(q), radio=self._radio)
        self._research_view = ResearchView(parent, on_close=self._close_research,
                                           on_cancel=self._research_ref["tools"].cancel,
                                           on_answer=self._research_ref["tools"].answer)

        tk.Frame(parent, bg=theme.BORDER, height=1).grid(row=3, column=0, sticky="ew", pady=(theme.px(8), 0))

        # Voz / Texto (+ Mudo and Câmera from the audio panel), centered.
        toggles = tk.Frame(parent, bg=theme.GLASS)
        toggles.grid(row=4, column=0, pady=(theme.px(12), theme.px(6)))
        self._btn_voice = theme.button(toggles, "Voz", lambda: self._set_mode("voice"), icon="mic")
        self._btn_voice.pack(side=tk.LEFT)
        self._btn_text = theme.button(toggles, "Texto", lambda: self._set_mode("text"), icon="keyboard")
        self._btn_text.pack(side=tk.LEFT)

        # Audio rows: full width on narrow windows, at most 620 px wide and centered on wide ones.
        audio_frame = tk.Frame(parent, bg=theme.GLASS)
        audio_frame.grid(row=5, column=0, sticky="ew", pady=(0, theme.px(12)))
        self._build_audio_selectors(audio_frame, toggles)

        def fit_controls(e):
            audio_frame.grid_configure(padx=max(theme.px(16), (e.width - theme.px(620)) // 2))
            self._legend.config(wraplength=max(1, e.width - theme.px(64)))
            self._mem_fit_map(e.height)
        parent.bind("<Configure>", fit_controls, add="+")

    # ── Monitoramento ──────────────────────────────────────────────────────────

    def _toggle_monitor(self):
        (self._close_monitor if self._monitor_ref["on"] else self._open_monitor)()

    def _open_monitor(self):
        self._close_research()                      # one mode at a time
        self._monitor_ref.update(on=True, fresh=True)
        self._appearance_area.grid_remove()
        self._memory_map_frame.grid_remove()
        self._monitor_view.grid(row=0, column=0, sticky="nsew", pady=(theme.px(8), 0))   # caption stays below
        self._cover_for_intro()
        self._monitor_view.open()
        theme.set_kind(self._monitor_button, "on")
        self._chat_insert("\n  🌍 Monitoramento: pergunte por notícias, clima, terremotos, voos, rádios ou satélites "
                          "de qualquer lugar, ou clique num país. Diga \"fechar monitoramento\" para voltar.\n", "info")

    def _cover_for_intro(self):
        """The opening zoom-out fills the whole PI dreams window, over the panels and menus: a borderless
        window on top of it that the globe draws into. When the globe is in its place, the same window
        becomes a veil over the rest that fades away (Tk has no per-widget transparency)."""
        self._drop_cover()
        root = self.root
        root.update_idletasks()
        cover = tk.Toplevel(root, bg=theme.BG)
        # No transient(): on Windows a borderless window that is also transient never shows (tested
        # 2026-11-07 — the opening ran, unseen, behind the app).
        cover.overrideredirect(True)
        cover.geometry(f"{root.winfo_width()}x{root.winfo_height()}+{root.winfo_rootx()}+{root.winfo_rooty()}")
        surface = tk.Frame(cover, bg=theme.BG)
        surface.pack(fill=tk.BOTH, expand=True)
        cover.lift()
        cover.update()                            # the surface has its real size before the first frame
        self._cover = cover
        globe = self._monitor_view.globe
        globe.show_on(surface)
        globe.on_intro_done = lambda: self._fade_cover(surface)

    def _fade_cover(self, surface):
        globe = self._monitor_view.globe
        globe.on_intro_done = None
        globe.show_on(None)
        cover = getattr(self, "_cover", None)
        if cover is None:
            return
        surface.destroy()
        key = theme.TRANSPARENT_KEY               # see-through: the hole over the globe
        cover.attributes("-transparentcolor", key)
        veil = tk.Canvas(cover, bg=theme.BG, highlightthickness=0)
        veil.pack(fill=tk.BOTH, expand=True)
        cover.update_idletasks()
        x, y = globe.surface.winfo_rootx() - cover.winfo_rootx(), globe.surface.winfo_rooty() - cover.winfo_rooty()
        veil.create_rectangle(x, y, x + globe.surface.winfo_width(), y + globe.surface.winfo_height(),
                              fill=key, outline=key)
        started = time.monotonic()

        def step():
            if getattr(self, "_cover", None) is not cover:
                return
            p = min(1.0, (time.monotonic() - started) / 0.6)
            cover.attributes("-alpha", 1 - p * p * (3 - 2 * p))   # smooth in and out
            if p < 1:
                cover.after(16, step)
            else:
                self._drop_cover()
        step()

    def _drop_cover(self):
        cover, self._cover = getattr(self, "_cover", None), None
        if cover is not None:
            self._monitor_view.globe.on_intro_done = None
            self._monitor_view.globe.show_on(None)
            cover.destroy()

    def _close_monitor(self):
        if not self._monitor_ref["on"]:
            return
        self._monitor_ref["on"] = False
        self._drop_cover()
        self._monitor_view.close()
        self._monitor_view.grid_remove()
        self._appearance_area.grid()
        self._memory_map_frame.grid()
        theme.set_kind(self._monitor_button, "primary")
        self._chat_insert("\n  Monitoramento fechado.\n", "info")

    # ── Pesquisa profunda ──────────────────────────────────────────────────────

    def _toggle_research(self):
        (self._close_research if self._research_ref["on"] else self._open_research)()

    def _open_research(self):
        self._close_monitor()                       # one mode at a time
        self._research_ref.update(on=True, fresh=True)
        self._appearance_area.grid_remove()
        self._memory_map_frame.grid_remove()
        if not self._research_ref["tools"].running:
            self._research_view.reset()
        self._research_view.grid(row=0, column=0, sticky="nsew", pady=(theme.px(8), 0))
        theme.set_kind(self._research_button, "on")
        self._chat_insert("\n  🔎 Pesquisa profunda: peça um tema e eu pesquiso na web, leio as fontes e escrevo "
                          "um relatório que fica na Base. Diga \"fechar pesquisa\" para voltar.\n", "info")

    def _close_research(self):
        if not self._research_ref["on"]:
            return
        self._research_ref["on"] = False
        self._research_ref["tools"].cancel()        # closing stops a research in progress, nothing half saved
        self._research_view.grid_remove()
        self._appearance_area.grid()
        self._memory_map_frame.grid()
        theme.set_kind(self._research_button, "primary")
        self._chat_insert("\n  Pesquisa profunda fechada.\n", "info")

    # ── Right panel: chat ──────────────────────────────────────────────────────

    def _build_right_panel(self, parent):
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        tk.Label(parent, text="Conversa", bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_SECTION,
                 anchor="w").grid(row=0, column=0, sticky="ew", padx=theme.px(18), pady=(theme.px(12), theme.px(10)))
        tk.Frame(parent, bg=theme.BORDER, height=1).grid(row=1, column=0, sticky="ew")

        chat_box = tk.Frame(parent, bg=theme.GLASS)
        chat_box.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(chat_box, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, theme.px(4)), pady=theme.px(4))

        self._chat = tk.Text(
            chat_box, width=1,   # the column decides the width, not 80 characters
            bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_CHAT,
            wrap=tk.WORD, state=tk.DISABLED,
            padx=theme.px(18), pady=theme.px(12), spacing1=theme.px(2), spacing3=theme.px(2),
            relief=tk.FLAT, borderwidth=0, highlightthickness=0,
            yscrollcommand=scrollbar.set, cursor="arrow",
            selectbackground=theme.GLASS_HI,
        )
        self._chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._chat.yview)

        self._chat.tag_configure("user_label",  foreground=theme.CYAN, font=theme.FONT_BOLD, spacing1=theme.px(12))
        self._chat.tag_configure("user_text",   foreground=theme.TEXT)
        self._chat.tag_configure("agent_label", foreground=theme.VIOLET, font=theme.FONT_BOLD, spacing1=theme.px(12))
        self._chat.tag_configure("agent_text",  foreground=theme.TEXT)
        self._chat.tag_configure("ltm",         foreground=theme.MUTED, font=theme.FONT_SMALL)
        self._chat.tag_configure("info",        foreground=theme.MUTED, font=theme.FONT_SMALL)

        # Text input (always visible, active only in text mode)
        self._text_frame = tk.Frame(parent, bg=theme.GLASS)
        self._text_frame.grid(row=3, column=0, sticky="ew", padx=theme.px(14), pady=theme.px(14))
        self._text_frame.grid_columnconfigure(0, weight=1)

        self._input_var = tk.StringVar()
        self._input_entry = theme.entry(self._text_frame, textvariable=self._input_var, width=1)
        self._input_entry.grid(row=0, column=0, sticky="ew", ipady=theme.px(8), padx=(0, theme.px(8)))
        self._input_entry.bind("<Return>", lambda _: self._send_text())

        self._send_btn = theme.button(self._text_frame, "Enviar", self._send_text, kind="primary", icon="send")
        self._send_btn.grid(row=0, column=1, sticky="ns")

    # ── Bottom bar: date / time / weather ─────────────────────────────────────

    def _build_bottom_bar(self, parent):
        self._date_var    = tk.StringVar(value="")
        self._time_var    = tk.StringVar(value="--:--")
        self._weather_var = tk.StringVar(value="")

        inner = tk.Frame(parent, bg=theme.GLASS)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        def _lbl(var, fg=theme.TEXT2, font=theme.FONT):
            tk.Label(inner, textvariable=var, bg=theme.GLASS, fg=fg, font=font).pack(side=tk.LEFT, padx=theme.px(10))

        _lbl(self._date_var)
        _lbl(self._time_var, fg=theme.TEXT, font=theme.FONT_CLOCK)
        _lbl(self._weather_var)
        # Open-Meteo's license (CC BY 4.0) asks for the credit, with a link, where the data shows.
        self._weather_credit = tk.Label(inner, text="", bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                                        cursor="hand2")
        self._weather_credit.pack(side=tk.LEFT)
        self._weather_credit.bind("<Button-1>", lambda _e: webbrowser.open("https://open-meteo.com/"))

        self._tick_clock()

    def _tick_clock(self):
        now = datetime.datetime.now()
        self._date_var.set(date_in_words(now.date()).capitalize())
        self._time_var.set(now.strftime("%H:%M"))

        w = self._weather.get()
        if not CONFIG.weather_city:
            self._weather_var.set("")            # no city: footer without weather
        elif w['city'] == CONFIG.weather_city:
            self._weather_var.set(f"{w['city']} · {w['temp']} °C · {w['desc']}")
        else:
            self._weather_var.set("obtendo o clima…")
        self._weather_credit.config(text="Open-Meteo" if CONFIG.weather_city else "")

        self.root.after(1000, self._tick_clock)

    # ── Mode control ──────────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        old_mode          = self._mode_ref[0]
        self._mode_ref[0] = mode
        theme.set_kind(self._btn_voice, "on" if mode == "voice" else "normal")
        theme.set_kind(self._btn_text, "on" if mode == "text" else "normal")

        if mode == "voice":
            self._input_entry.config(state=tk.DISABLED)
            self._send_btn.config(state=tk.DISABLED)
            if old_mode == "text":
                self._text_input.put(None)
        else:
            self._input_entry.config(state=tk.NORMAL)
            self._send_btn.config(state=tk.NORMAL)
            self._input_entry.focus_set()

    def _send_text(self):
        text = self._input_var.get().strip()
        if text:
            self._text_input.put(text)
            self._input_var.set("")

    # ── Event processing ──────────────────────────────────────────────────────

    def _process_events(self):
        try:
            while True:
                etype, data = self._queue.get_nowait()
                self._handle_event(etype, data)
        except queue.Empty:
            pass
        asleep = self._sleep_ref[0]
        if not asleep:                    # nothing on screen to update while in the tray
            self._update_stats()
            self._follow_voice()
        self._show_pending_shutdown()
        self.root.after(250 if asleep else 35, self._process_events)

    def _show_pending_shutdown(self):
        """While PI's shutdown/restart counts down, a notice with one-click cancel stays on top."""
        pending = pc.pending_shutdown()
        if pending == getattr(self, "_shutdown_shown", None):
            return
        self._shutdown_shown = pending
        if pending is None:
            self._notices.resolve("shutdown")
            return
        verb = "desliga" if pending[0] == "desligar" else "reinicia"
        self._notices.show(problems.problem(
            "shutdown", f"O PC {verb} às {pending[1]:%H:%M}.",
            [("Cancelar desligamento", "shutdown_cancel")], level="warning"))

    _LEGEND_GAP_S = 0.8     # silence between two sentences (synthesis catching up) keeps the caption

    def _follow_voice(self):
        spoken = remove_emojis(tts_audio.SPEAKING_TEXT[0]).strip()
        if spoken:
            self._show_legend(spoken, self._LEGEND_GAP_S)
        elif time.monotonic() > self._legend_hold and self._legend.cget("text"):
            self._legend.config(text="")

    def _show_legend(self, text: str, hold_s: float):
        self._legend_hold = time.monotonic() + hold_s
        if self._legend.cget("text") != text:
            self._legend.config(text=text)

    def _update_stats(self):
        s = self._sys_monitor.get()

        # CPU
        cpu_sub = f"{s['cpu_temp']:.0f} °C" if s['cpu_temp'] is not None else ""
        self._cpu_meter.update(s['cpu_pct'], cpu_sub)

        # RAM
        ram_sub = f"{s['ram_used_gb']:.1f} de {s['ram_total_gb']:.0f} GB".replace(".", ",")
        self._ram_meter.update(s['ram_pct'], ram_sub)

        # GPU
        if s['gpu_pct'] is not None:
            gpu_sub = f"{s['gpu_temp']:.0f} °C" if s['gpu_temp'] is not None else ""
            self._gpu_meter.update(s['gpu_pct'], gpu_sub)
        else:
            self._gpu_meter.update(0, "aguardando…")

    def _handle_event(self, etype: str, data):
        if etype == "status":
            s = (data or "").lower()
            if   "mudo" in s:
                self._sphere_state("idle")
            elif "fala" in s or "aguardando" in s or "escutando" in s:
                self._sphere_state("listening")
            elif "processando" in s or "carregando" in s:
                self._sphere_state("thinking")
            elif "respondendo" in s:
                self._sphere_state("speaking")
            else:
                self._sphere_state("idle")
            color = theme.DANGER if "❌" in (data or "") else theme.STATE_COLORS[self._appearance_state]
            self._show_status(remove_emojis(data or "").strip().rstrip("."), color)

        elif etype == "user":
            self._mark_use()
            self._flush_agent_buf()
            self._chat_insert("\nVocê\n", "user_label")
            self._chat_insert(data + "\n", "user_text")
            self._sphere_state("thinking")

        elif etype == "agent_start":
            self._agent_working = True
            self._flush_agent_buf()
            self._chat_insert("PI\n", "agent_label")
            self._agent_buf = ""
            self._sphere_state("speaking")

        elif etype == "agent_chunk":
            data = remove_emojis(data or "").strip()
            if data:
                self._agent_buf += data + " "
                self._chat_insert(data + " ", "agent_text")
                if self._mode_ref[0] == "text":        # no audio to follow: show it as it arrives
                    self._show_legend(data, hold_s=6.0)

        elif etype == "agent_end":
            self._mark_use()
            self._agent_working = False
            self._chat_insert("\n", "agent_text")
            self._agent_buf = ""
            self._sphere_state("idle")

        elif etype == "ltm_stored":
            self._chat_insert(f"  🧠 {data}\n", "ltm")

        elif etype == "context_used":
            self._mem_on_context_used(data)

        elif etype == "monitor_focus":
            self._monitor_view.focus(data)

        elif etype == "monitor_planes":
            self._monitor_view.set_planes(data["on"])

        elif etype == "monitor_close":
            self._close_monitor()

        elif etype == "monitor_open":
            if not self._monitor_ref["on"]:
                self._open_monitor()

        elif etype == "research_open":
            if not self._research_ref["on"]:
                self._open_research()

        elif etype == "research_close":
            self._close_research()

        elif etype == "research_progress":
            self._research_view.progress(data)
            if data.get("etapa") == "pronta" and data.get("arquivo"):
                self._kb_refresh()                  # the new report shows in the Base tab

        elif etype == "tool":
            self._chat_insert(f"  ↳ {data}\n", "info")

        elif etype == "problem":
            self._notices.show(data)

        elif etype == "mcp_changed":
            self._refresh_connections(data)
            self._debounce("today", 2000, self._today.refresh)

        elif etype == "resolved":
            self._notices.resolve(data)

        elif etype == "wake":
            self._wake()

        elif etype == "quit":
            self._quit()

        elif etype == "claps":
            self._set_claps(data)

        elif etype == "stopped":
            self._show_status("Encerrado", theme.MUTED)
            self._sphere_state("idle")
            self.root.after(700, self.root.destroy)

    def _open_settings(self):
        window = getattr(self, "_settings_window", None)
        if window is not None and window.window.winfo_exists():
            window.window.lift()
            return
        from pidreams.ui.settings_dialog import SettingsDialog
        self._settings_window = SettingsDialog(self.root, SETTINGS)

    def _apply_settings(self, st):
        self._mic_device_ref[0] = devices.index(st.get("audio.input_device"), "input")
        self._out_device_ref[0] = devices.index(st.get("audio.output_device"), "output")
        self._volume_ref[0] = st.get("audio.volume")
        # The audio panel selectors follow the settings screen.
        for var, mapping, key in ((self._mic_var, self._input_device_map, "audio.input_device"),
                                 (self._out_var, self._output_device_map, "audio.output_device")):
            label_text = next((r for r, name in mapping.items() if name == st.get(key)), None)
            # Device chosen but unplugged right now: do not change the selector (that
            # would write "Padrão" over the user's choice).
            if label_text is not None and var.get() != label_text:
                var.set(label_text)
        self._warn_missing_devices()
        if st.get("appearance") != self._sphere.id:
            self._switch_appearance(st.get("appearance"))

    def _warn_missing_devices(self):
        """Chosen device unplugged: the audio already falls back to the Windows default; the
        notice tells the person so (before, it only went to the log)."""
        for kind, key, ref, device_name in (
                ("input", "audio.input_device", self._mic_device_ref, "microphone"),
                ("output", "audio.output_device", self._out_device_ref, "saída de som")):
            chosen, code = SETTINGS.get(key), f"device_{kind}"
            if chosen and ref[0] is None:
                self._notices.show(problems.problem(
                    code, f"{device_name.capitalize()} '{chosen}' não encontrado. "
                            "Usando o padrão do Windows.", [], level="warning"))
            else:
                self._notices.resolve(code)

    def _run_action(self, action: str, notice: dict):
        """Notice-bar buttons. Heavy work goes to a thread; the agent loop notices the
        recovery by itself and closes the notice."""
        from pidreams.hardware import models, ollama_supervisor

        def in_thread(function):
            threading.Thread(target=function, daemon=True).start()

        if action == "ollama_start":
            in_thread(ollama_supervisor.start)
        elif action == "ollama_restart":
            in_thread(ollama_supervisor.restart)
        elif action == "ollama_site":
            os.startfile("https://ollama.com/download")
        elif action == "download_model":
            from pidreams.ui.download_dialog import DownloadDialog
            DownloadDialog(self.root, "Baixando o modelo de conversa",
                           [(CONFIG.ollama_model, lambda p, c: models.download_ollama(CONFIG.ollama_model, p, c))])
        elif action == "retry" and notice.get("retry_text"):
            self._notices.resolve(notice["code"])
            self._text_input.put(notice["retry_text"])
        elif action == "open_log":
            os.startfile(paths.logs_dir())
        elif action == "shutdown_cancel":
            in_thread(pc.cancelar_desligamento)
        elif action in ("confirm_yes", "confirm_no"):
            confirmation.answer(action == "confirm_yes")
        elif action.startswith("mcp_restart:"):
            self._start_connection(action.split(":", 1)[1])
        elif action.startswith("mcp_log:"):
            registry = paths.logs_dir() / f"mcp-{action.split(':', 1)[1]}.log"
            os.startfile(registry if registry.is_file() else paths.logs_dir())
        elif action in ("camera_privacy", "microphone_privacy"):
            os.startfile("ms-settings:privacy-webcam" if action == "camera_privacy"
                         else "ms-settings:privacy-microphone")

    def _sphere_state(self, state: str):
        self._appearance_state = state
        if self._sphere:
            self._sphere.set_state(state)

    def _switch_appearance(self, id_: str):
        """Switches right away: the voice and the microphone run on other threads and do not
        depend on the widget; the new appearance starts in the current state."""
        if self._sphere:
            self._sphere.stop()
            self._sphere.destroy()
        self._sphere = appearances.create(id_, self._appearance_frame, size=self._appearance_size, bg=theme.GLASS,
                                        on_fail=lambda: self._switch_appearance(appearances.fallback(self._sphere.id)))
        self._sphere.set_state(self._appearance_state)
        self._sphere.pack()

    # ── Responsive layout ─────────────────────────────────────────────────────

    def _debounce(self, key: str, ms: int, function, *args):
        """Runs once the window stops changing for ms (dragging the edge fires dozens of events)."""
        if key in self._pending:
            self.root.after_cancel(self._pending[key])
        self._pending[key] = self.root.after(ms, lambda: (self._pending.pop(key, None), function(*args)))

    def _fit_columns(self, main: tk.Frame, width: int):
        left, _center, chat = theme.columns(width)
        self._left_panel.config(width=left)
        self._right_panel.config(width=chat)

    def _fit_appearance(self):
        area = self._appearance_area
        size, show_today = theme.appearance_fit(area.winfo_width(), area.winfo_height(),
                                                appearances.max_size(self._sphere.id))
        # Recreate only on a real change: small drags would restart the animation for nothing.
        if abs(size - self._appearance_size) > self._appearance_size * 0.08:
            self._appearance_size = size
            self._switch_appearance(self._sphere.id)
        if show_today:
            self._today.show(self._appearance_size, area.winfo_width(), area.winfo_height())
        else:
            self._today.hide()

    def _place_window(self):
        saved = SETTINGS.get("window")

        def on_screen(x, y):
            point = ctypes.wintypes.POINT(x, y)
            return bool(ctypes.windll.user32.MonitorFromPoint(point, 0))   # 0 = MONITOR_DEFAULTTONULL

        self.root.geometry(theme.initial_geometry(saved.get("geometry", ""), self.root.winfo_screenwidth(),
                                                  self.root.winfo_screenheight(), on_screen))
        self._normal_geometry = self.root.geometry()
        if saved.get("zoomed") and not self._start_asleep:     # zooming would show the window
            self.root.after_idle(lambda: self.root.state("zoomed"))
        self.root.bind("<Configure>", self._remember_geometry, add="+")

    def _remember_geometry(self, event):
        if event.widget is self.root and self.root.state() == "normal":
            self._normal_geometry = self.root.geometry()

    def _save_window(self):
        try:
            SETTINGS.set("window", {"geometry": self._normal_geometry,
                                    "zoomed": self.root.state() == "zoomed"})
            SETTINGS.save()
        except (OSError, ValueError, tk.TclError) as e:
            log.warning("could not save the window position: %s", e)

    def _flush_agent_buf(self):
        self._agent_buf = ""

    def _chat_insert(self, text: str, tag: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, text, tag)
        self._chat.see(tk.END)
        self._chat.config(state=tk.DISABLED)

    # ── Agent thread ──────────────────────────────────────────────────────────

    def _emit(self, etype: str, data=None):
        self._queue.put((etype, data))

    def _load_stores_thread(self):
        """Loads LTMStore + KBStore in the background — does not freeze the window."""
        try:
            ltm = LTMStore()
            kb = KBStore(
                client=ltm._client if ltm.available else None,
                embedder=ltm._embedder if ltm.available else None,
            )
            self._ltm_store = ltm
            self._kb_store = kb
        except Exception as e:
            log.warning(f"[Stores] Error: {e}")
        finally:
            self._stores_ready.set()
            self.root.after(0, self._on_stores_ready)

    def _on_stores_ready(self):
        """Called by the stores thread when they are ready — triggers the first refresh."""
        self._mem_show_all()
        self._kb_refresh()

    def _run_agent_thread(self):
        # Wait for the stores before starting (they load in the background)
        self._stores_ready.wait()

        async def _run():
            self._stop_event = asyncio.Event()
            await run_agent(
                on_event=self._emit,
                stop_event=self._stop_event,
                mode_ref=self._mode_ref,
                text_input_queue=self._text_input,
                mic_device_ref=self._mic_device_ref,
                out_device_ref=self._out_device_ref,
                volume_ref=self._volume_ref,
                mute_ref=self._mute_ref,
                ltm_store=self._ltm_store,
                kb_store=self._kb_store,
                connections=self._connections,
                monitor_ref=self._monitor_ref,
                research_ref=self._research_ref,
                sleep_ref=self._sleep_ref,
            )
            self._emit("stopped")

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(_run())

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _on_close(self):
        if SETTINGS.get("tray.close_to_tray") and self._tray is not None:
            self._sleep()
        else:
            self._quit()

    def _quit(self):
        if self._quitting:
            return
        self._quitting = True
        if self._claps:
            self._claps.stop()
        if self._tray:
            self._tray.destroy()
        if self.root.state() != "withdrawn":       # asleep: saved when it went to the tray
            self._save_window()
        self._services.stop_all()
        self._connections.stop_all()
        if self._sphere:
            self._sphere.stop()
        self._sys_monitor.stop()
        self._weather.stop()
        if self._loop and self._stop_event:
            self._text_input.put(None)
            self._loop.call_soon_threadsafe(self._stop_event.set)
        else:
            self.root.destroy()

    # ── Tray (asleep / awake) ─────────────────────────────────────────────────

    def _start_tray(self):
        try:
            # The icon's callbacks run inside a Windows message handler: they only queue the event,
            # and the window acts on it from its own loop (Tk code run from there crashed the app on
            # going to sleep and quitting: "PyEval_RestoreThread").
            self._tray = TrayIcon(on_wake=lambda: self._emit("wake"), on_claps=lambda on: self._emit("claps", on),
                                  on_quit=lambda: self._emit("quit"))
        except Exception as e:
            log.warning("tray icon unavailable (closing the window exits): %r", e)
        self.root.bind_all("<ButtonPress>", self._mark_use, add="+")
        self.root.bind_all("<KeyPress>", self._mark_use, add="+")
        if self._sleep_ref[0]:
            self._sleep()
        self.root.after(_TRAY_TICK_MS, self._tray_tick)
        threading.Thread(target=self._watch_games, daemon=True, name="games").start()

    def _mark_use(self, _event=None):
        self._last_use = time.monotonic()

    def _sleep(self):
        """To the tray: no window; the loop stops listening and takes the model off the GPU."""
        if self._tray is None or self._quitting:
            return
        if self.root.state() != "withdrawn":
            self._save_window()
        self._sleep_ref[0] = True
        self._close_monitor()             # the globe draws at 120 fps: nothing runs unseen
        if self._sphere:
            self._sphere.stop()
        self.root.withdraw()
        self._update_claps()

    def _wake(self):
        if self._quitting:
            return
        was_asleep, self._sleep_ref[0] = self._sleep_ref[0], False
        self._update_claps()
        if was_asleep and self._sphere:
            self._switch_appearance(self._sphere.id)      # its animation stopped on sleeping
        self.root.deiconify()
        if SETTINGS.get("window.zoomed"):
            self.root.state("zoomed")
        # Woken by claps there was no click: Windows only lets a topmost flip bring it forward.
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self._mark_use()

    def _set_claps(self, on: bool):
        SETTINGS.set("tray.claps", on)
        SETTINGS.save()
        self._update_claps()

    def _update_claps(self):
        """The microphone listens for claps only while asleep and allowed; the icon always says
        which (listening, paused, no microphone)."""
        wanted = self._sleep_ref[0] and SETTINGS.get("tray.claps")
        if not wanted:
            if self._claps:
                self._claps.stop()
                self._claps = None
        elif self._claps is None or not self._claps.active:
            try:
                self._claps = ClapListener(
                    # Through the event queue: Tk must not be touched from the audio thread
                    # (root.after from there crashed the app: "PyEval_RestoreThread").
                    self._mic_device_ref[0], on_claps=lambda: self._emit("wake"),
                    ignore=lambda: bool(tts_module.SPEAKING_TEXT[0]) or self._radio.station is not None,
                    min_level=SETTINGS.get("tray.clap_level"))
                self._claps.start()
            except Exception as e:
                log.warning("clap listener: %r", e)
                self._claps = None
        if self._tray is None:
            return
        if not self._sleep_ref[0]:
            self._tray.hide()
        elif not SETTINGS.get("tray.claps"):
            self._tray.show("paused")
        else:
            self._tray.show("listening" if self._claps else "no_mic")

    def _tray_tick(self):
        """Asleep: microphone back if it was unplugged. Awake: to the tray after the idle time."""
        if self._quitting:
            return
        if self._sleep_ref[0]:
            self._update_claps()
        elif (SETTINGS.get("tray.close_to_tray") and not self._agent_working
              and not tts_module.SPEAKING_TEXT[0] and not self._research_ref["tools"].running
              and time.monotonic() - self._last_use > SETTINGS.get("tray.idle_minutes") * 60):
            log.info("idle for %d min: to the tray", SETTINGS.get("tray.idle_minutes"))
            self._sleep()
        self.root.after(_TRAY_TICK_MS, self._tray_tick)

    def _watch_games(self):
        """A game running closes the app completely, model off the GPU first (also right at start)."""
        while not self._quitting:
            try:
                reason = game_running(SETTINGS.get("tray.games"))
            except Exception as e:
                log.warning("game check: %r", e)
                reason = None
            if reason:
                log.info("game detected (%s): closing completely", reason)
                unload = threading.Thread(target=_unload_quietly, daemon=True)
                unload.start()
                unload.join(3)
                self._emit("quit")
                return
            time.sleep(_GAMES_CHECK_S)

    def run(self):
        self._start_tray()
        self._tick_services()
        self._restart_saved_connections()
        threading.Thread(target=self._load_stores_thread, daemon=True).start()
        threading.Thread(target=self._run_agent_thread, daemon=True).start()
        self._process_events()
        self.root.mainloop()
