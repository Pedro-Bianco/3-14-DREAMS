"""PI dreams visual identity ("neon glass"): the only place for colors, fonts and sizes.

Every screen reads from here. Contrast of each text color against the backgrounds was
computed with the WCAG formula (tests/unit/test_theme.py keeps it >= 4.5).
"""

import ctypes
import re
import tkinter as tk
from tkinter import ttk

# ── Colors ───────────────────────────────────────────────────────────────────
BG        = "#070B1F"   # window background (deep navy)
GLASS     = "#0F1738"   # panels
GLASS_HI  = "#16204A"   # active tab, cards inside panels
HOVER     = "#1E2C66"   # mouse over a button or row
INPUT     = "#0A1230"   # text fields and lists
BORDER    = "#2A3A7A"   # 1 px glass edge
SHINE     = "#3B4FA0"   # 1 px highlight on the top edge of a panel

TEXT      = "#E8EEFF"   # 16.8:1 on BG, 15.1:1 on GLASS
TEXT2     = "#A3B1DD"   # secondary, 8.2:1 on GLASS
MUTED     = "#7F8DBB"   # captions and disabled, 4.8:1 on GLASS_HI (the darkest pair)

CYAN      = "#22D3EE"   # accent: listening, speaking, the user in the chat
VIOLET    = "#A78BFA"   # accent 2: thinking, the assistant in the chat
OK        = "#34D399"
PEACH     = "#F59E8B"   # third meter color (GPU)
WARN      = "#FBBF24"
DANGER    = "#F87171"
WARN_BG   = "#2A2410"   # notice bar behind WARN text
DANGER_BG = "#2E1418"
# Monitoramento globe
GLOBE_SPHERE = "#0B1A3F"  # the Earth behind the dots
GLOBE_BORDER = "#7FE9FF"  # country borders
SAT_INTERNET = "#BFEFFF"  # internet constellations (most of the points)
SAT_STATION  = "#FFF3A0"  # space stations and the ISS mark

TEXT_PAIRS = [(fg, bg) for fg in (TEXT, TEXT2, MUTED, CYAN, VIOLET, OK, PEACH, WARN, DANGER)
              for bg in (BG, GLASS, GLASS_HI, INPUT)] + [(WARN, WARN_BG), (DANGER, DANGER_BG),
              (TEXT, "#17407A"), (CYAN, "#123A55"), (TEXT, HOVER)]

# ── Fonts (all ship with Windows 10 and 11; nothing is bundled) ──────────────
UI_FAMILY, TECH_FAMILY, CODE_FAMILY = "Segoe UI", "Bahnschrift", "Consolas"

FONT       = (UI_FAMILY, 10)
FONT_SMALL = (UI_FAMILY, 9)
FONT_BOLD  = (UI_FAMILY, 10, "bold")
FONT_CHAT  = (UI_FAMILY, 10)
FONT_LEGEND = (UI_FAMILY, 12)
FONT_TITLE = (TECH_FAMILY, 16)
FONT_SECTION = (TECH_FAMILY, 12)
FONT_TAB   = ("Bahnschrift SemiCondensed", 11)
FONT_STATUS = (TECH_FAMILY, 13)
FONT_NUMBER = (TECH_FAMILY, 20)
FONT_CLOCK = (TECH_FAMILY, 13)
FONT_CODE  = (CODE_FAMILY, 9)

# Segoe MDL2 Assets glyphs. Tk falls back to that font by itself when a Segoe UI text
# contains them, so an icon and its label can share one string.
ICON = {
    "mic": "", "keyboard": "", "send": "", "warning": "",
    "error": "", "close": "", "camera": "", "mute": "",
    "settings": "", "power": "", "log": "", "folder": "",
    "add": "", "delete": "", "refresh": "", "search": "",
    "globe": "",
}

# Assistant state → (dot color). The text comes from the agent, already in Portuguese.
STATE_COLORS = {"idle": TEXT2, "listening": CYAN, "thinking": VIOLET, "speaking": CYAN}

# ── Sizes ────────────────────────────────────────────────────────────────────
_scale = [1.0]

def px(n: float) -> int:
    """Pixels at 100% → pixels at the current Windows scale."""
    return round(n * _scale[0])


def enable_dpi_awareness() -> None:
    """Must run before the first Tk(): without it Windows stretches the window bitmap at
    125%/150% and everything looks blurry."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)     # system aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def init(root: tk.Misc) -> None:
    """Reads the scale from Tk (pixels per point; 96/72 at 100%) and styles the ttk widgets."""
    _scale[0] = float(root.tk.call("tk", "scaling")) / (96 / 72)
    _apply_ttk(root)


def _apply_ttk(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=GLASS, foreground=TEXT, fieldbackground=INPUT,
                    bordercolor=BORDER, lightcolor=GLASS, darkcolor=GLASS, troughcolor=INPUT,
                    focuscolor=CYAN, selectbackground=GLASS_HI, selectforeground=TEXT, font=FONT)
    style.configure("TCombobox", arrowcolor=TEXT2, padding=(px(8), px(3)), background=INPUT,
                    foreground=TEXT, lightcolor=INPUT, darkcolor=INPUT, bordercolor=BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", INPUT), ("disabled", GLASS)],
              foreground=[("disabled", MUTED)], bordercolor=[("focus", CYAN), ("hover", SHINE)],
              arrowcolor=[("hover", CYAN)], background=[("readonly", INPUT), ("active", GLASS_HI)],
              lightcolor=[("focus", INPUT)], darkcolor=[("focus", INPUT)])
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", GLASS_HI)
    root.option_add("*TCombobox*Listbox.selectForeground", CYAN)
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=BORDER, troughcolor=GLASS,
                        bordercolor=GLASS, arrowcolor=TEXT2, relief="flat",
                        gripcount=0, arrowsize=px(10))
        style.map(f"{orient}.TScrollbar", background=[("active", SHINE), ("pressed", CYAN)])
    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=0)
    style.configure("TNotebook.Tab", background=GLASS, foreground=TEXT2, bordercolor=BORDER,
                    padding=(px(14), px(6)), font=FONT_TAB)
    style.map("TNotebook.Tab", background=[("selected", GLASS_HI)],
              foreground=[("selected", CYAN), ("active", TEXT)])
    style.configure("Horizontal.TProgressbar", background=CYAN, troughcolor=INPUT,
                    bordercolor=BORDER, lightcolor=CYAN, darkcolor=VIOLET)
    style.configure("TCheckbutton", background=GLASS, foreground=TEXT, indicatorcolor=INPUT)
    style.map("TCheckbutton", indicatorcolor=[("selected", CYAN)], background=[("active", GLASS)])
    style.configure("TRadiobutton", background=GLASS, foreground=TEXT, indicatorcolor=INPUT)
    style.map("TRadiobutton", indicatorcolor=[("selected", CYAN)], background=[("active", GLASS)])


# ── Widget factories (shared by several screens) ─────────────────────────────

# Tk buttons on Windows do not paint a colored border, so each kind is a filled "chip"
# slightly lighter than the glass behind it.
_BUTTON_KINDS = {
    #            bg         fg      hover bg   hover fg
    "normal":  (GLASS_HI,  TEXT2,  HOVER,     TEXT),
    "primary": ("#17407A", TEXT,   "#1D4F96", TEXT),
    "danger":  (DANGER_BG, DANGER, "#431C22", DANGER),
    "on":      ("#123A55", CYAN,   "#164A6B", CYAN),      # toggle pressed (Voz/Texto)
}


def button(parent, text: str, command=None, kind: str = "normal", icon: str | None = None,
           font=FONT, **kw) -> tk.Button:
    label = f"{ICON[icon]}  {text}" if icon else text
    b = tk.Button(parent, text=label, command=command, font=font, relief=tk.FLAT, bd=0,
                  cursor="hand2", padx=px(12), pady=px(4), highlightthickness=0,
                  disabledforeground=MUTED, **kw)
    set_kind(b, kind)
    b.bind("<Enter>", lambda _e: b["state"] != tk.DISABLED and b.config(bg=b._hover[0], fg=b._hover[1]))
    b.bind("<Leave>", lambda _e: b.config(bg=b._rest[0], fg=b._rest[1]))
    return b


def set_kind(b: tk.Button, kind: str) -> None:
    """Restyles a factory button (toggles switch between "normal" and "on")."""
    bg, fg, hover_bg, hover_fg = _BUTTON_KINDS[kind]
    b._rest, b._hover = (bg, fg), (hover_bg, hover_fg)
    b.config(bg=bg, fg=fg, activebackground=hover_bg, activeforeground=hover_fg)


def entry(parent, textvariable=None, **kw) -> tk.Entry:
    return tk.Entry(parent, textvariable=textvariable, bg=INPUT, fg=TEXT, insertbackground=CYAN,
                    font=FONT, relief=tk.FLAT, bd=0, highlightthickness=1,
                    highlightbackground=BORDER, highlightcolor=CYAN,
                    disabledbackground=GLASS, disabledforeground=MUTED, **kw)


def label(parent, text: str = "", kind: str = "text", **kw) -> tk.Label:
    fg, font = {"text": (TEXT, FONT), "secondary": (TEXT2, FONT), "caption": (MUTED, FONT_SMALL),
                "section": (TEXT, FONT_SECTION)}[kind]
    kw.setdefault("bg", parent["bg"])
    return tk.Label(parent, text=text, fg=fg, font=font, anchor="w", **kw)


def section(parent, text: str) -> tk.Label:
    """Title of a block inside a panel (e.g. "Apps permitidos")."""
    return tk.Label(parent, text=text, bg=parent["bg"], fg=TEXT, font=FONT_SECTION, anchor="w")


def check(parent, text: str, variable, command=None) -> tk.Checkbutton:
    bg = parent["bg"]
    return tk.Checkbutton(parent, text=text, variable=variable, command=command, bg=bg, fg=TEXT2,
                          selectcolor=INPUT, activebackground=bg, activeforeground=TEXT, font=FONT,
                          anchor="w", bd=0, highlightthickness=0, cursor="hand2")


def glass(parent, hi: bool = False, **kw) -> tk.Frame:
    """Glass panel: flat color, 1 px border and a lighter line on the top edge.
    (Real translucency in Tk applies to the whole window, so it is drawn instead.)"""
    frame = tk.Frame(parent, bg=GLASS_HI if hi else GLASS, highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=BORDER, bd=0, **kw)
    tk.Frame(frame, bg=SHINE, height=1).place(x=0, y=0, relwidth=1)
    return frame


def gradient(canvas: tk.Canvas, width: int, height: int, horizontal: bool = True) -> None:
    """Cyan → violet stripe drawn once (header line, active tab, rings)."""
    canvas.delete("gradient")
    steps = max(1, width if horizontal else height)
    c1 = [int(CYAN[i:i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(VIOLET[i:i + 2], 16) for i in (1, 3, 5)]
    for i in range(0, steps, 2):
        t = i / steps
        color = "#%02x%02x%02x" % tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
        if horizontal:
            canvas.create_rectangle(i, 0, i + 2, height, fill=color, width=0, tags="gradient")
        else:
            canvas.create_rectangle(0, i, width, i + 2, fill=color, width=0, tags="gradient")


def blend(color: str, alpha: float, base: str = GLASS) -> str:
    """Color mixed over a background (Tk has no alpha)."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(y + (x - y) * alpha))) for x, y in zip(a, b))


# ── Responsive layout (pure: tests run it without a window) ─────────────────
MIN_WINDOW = (1024, 640)        # fits a 1366×768 screen with the taskbar
GAP = 12
CARD_W = 300                    # "Hoje" cards beside the appearance


def _clamp(value: float, low: int, high: int) -> int:
    return int(min(max(value, low), high))


def columns(width: int) -> tuple[int, int, int]:
    """(left, center, chat) widths. The chat stops at ~95 characters of Segoe UI 10 so long
    lines stay readable; extra width goes to the center."""
    left = _clamp(width * 0.22, px(280), px(340))
    chat = _clamp(width * 0.34, px(360), px(720))
    return left, max(0, width - left - chat - 4 * px(GAP)), chat


def appearance_fit(area_w: int, area_h: int, max_size: int) -> tuple[int, bool]:
    """(appearance size, show the "Hoje" cards) for the free area of the center panel.
    max_size is in screen pixels (the drawing cost follows the real pixel count)."""
    size = int(min(area_h, area_w * 0.9, max_size))
    room_for_cards = area_w >= size + 2 * px(CARD_W) + 4 * px(GAP)
    return max(px(120), size), room_for_cards


def initial_geometry(saved: str, screen_w: int, screen_h: int, on_screen) -> str:
    """Geometry to open the main window with: the saved one while it is still visible and not
    below the minimum; otherwise centered at 80% of the screen (up to 1440×900 at 100%)."""
    m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", saved or "")
    if m:
        w, h, x, y = map(int, m.groups())
        if w >= px(MIN_WINDOW[0]) and h >= px(MIN_WINDOW[1]) and on_screen(x + px(40), y + px(10)):
            return saved
    w = min(max(int(screen_w * 0.8), px(MIN_WINDOW[0])), px(1440), screen_w)
    h = min(max(int(screen_h * 0.8), px(MIN_WINDOW[1])), px(900), screen_h)
    return f"{w}x{h}+{(screen_w - w) // 2}+{(screen_h - h) // 2}"


class Slider(tk.Canvas):
    """Thin track, cyan fill and a round knob (ttk's Scale draws a thick box in any theme).
    Same interface the screens used: variable, from_/to and command(value)."""

    def __init__(self, parent, variable: tk.DoubleVar, from_: float, to: float, command=None):
        super().__init__(parent, height=px(20), width=1, bg=parent["bg"], highlightthickness=0, cursor="hand2")
        self._var, self._from, self._to, self._command = variable, from_, to, command
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        variable.trace_add("write", lambda *_: self._draw())

    def _x(self, value: float) -> float:
        r = px(7)
        return r + (self.winfo_width() - 2 * r) * (value - self._from) / (self._to - self._from)

    def _drag(self, event):
        r = px(7)
        frac = min(1.0, max(0.0, (event.x - r) / max(1, self.winfo_width() - 2 * r)))
        value = self._from + frac * (self._to - self._from)
        self._var.set(value)
        if self._command:
            self._command(value)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        y, r, x = h / 2, px(7), self._x(self._var.get())
        self.create_line(r, y, w - r, y, fill=BORDER, width=px(4), capstyle=tk.ROUND)
        self.create_line(r, y, x, y, fill=CYAN, width=px(4), capstyle=tk.ROUND)
        self.create_oval(x - r, y - r, x + r, y + r, fill=TEXT, outline=CYAN, width=2)
