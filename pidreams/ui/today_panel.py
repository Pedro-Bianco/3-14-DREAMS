""""Hoje" cards beside the appearance on wide windows: weather and today's calendar on the left,
reminders and unread e-mail on the right.

Same sources and rules as the briefing on open (briefing.sources); nothing new is fetched and
no reminder is marked as notified.
"""

import datetime as dt
import logging
import threading
import tkinter as tk

from pidreams import briefing, reminders
from pidreams.core.settings import SETTINGS
from pidreams.ui import theme

log = logging.getLogger(__name__)

_REFRESH_MS = 10 * 60 * 1000
_REMINDERS_CHECK_MS = 3000      # reminders.json is local: a stat every 3 s costs nothing
# part → (title, accent, column)
_CARDS = {"clima": ("Clima · Open-Meteo", theme.CYAN, 0),      # CC BY 4.0: credit where the data shows "agenda": ("Agenda de hoje", theme.VIOLET, 0),
          "lembretes": ("Lembretes", theme.CYAN, 1), "emails": ("E-mails não lidos", theme.VIOLET, 1)}


class TodayPanel:
    def __init__(self, area: tk.Frame, connections):
        self._area, self._connections = area, connections
        self._texts: dict[str, str] = {}
        self._columns = [tk.Frame(area, bg=theme.GLASS) for _ in range(2)]
        self._cards: dict[str, tuple[tk.Frame, tk.Label]] = {}
        for part, (title, accent, column) in _CARDS.items():
            card = theme.glass(self._columns[column], hi=True)
            tk.Label(card, text=title, bg=theme.GLASS_HI, fg=accent, font=theme.FONT_TAB,
                     anchor="w").pack(fill=tk.X, padx=theme.px(14), pady=(theme.px(10), theme.px(4)))
            body = tk.Label(card, bg=theme.GLASS_HI, fg=theme.TEXT2, font=theme.FONT, anchor="w", justify="left",
                            wraplength=theme.px(theme.CARD_W - 32))
            body.pack(fill=tk.X, padx=theme.px(14), pady=(0, theme.px(12)))
            self._cards[part] = (card, body)
        self._visible = False
        self._reminders_mtime = None
        self._periodic()
        self._watch_reminders()

    # ── placement (the main window decides when there is room) ───────────────

    def show(self, appearance_size: int, area_w: int, area_h: int):
        width, gap = theme.px(theme.CARD_W), theme.px(theme.GAP) * 3
        top = max(0, (area_h - appearance_size) // 2)
        left_x = (area_w - appearance_size) // 2 - gap - width
        right_x = (area_w + appearance_size) // 2 + gap
        self._columns[0].place(x=left_x, y=top, width=width)
        self._columns[1].place(x=right_x, y=top, width=width)
        self._visible = True

    def hide(self):
        for column in self._columns:
            column.place_forget()
        self._visible = False

    # ── content ──────────────────────────────────────────────────────────────

    def refresh(self):
        """Fetches every part in a thread (the calendar and Gmail go through MCP). Also called
        when a connection changes state, so Agenda and Gmail appear as soon as they connect."""
        threading.Thread(target=self._fetch, daemon=True, name="hoje").start()

    def _periodic(self):
        self.refresh()
        self._area.after(_REFRESH_MS, self._periodic)

    def _watch_reminders(self):
        """A reminder created, done or removed by voice shows up within a few seconds."""
        try:
            mtime = reminders.file().stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._reminders_mtime:
            self._reminders_mtime = mtime
            if (SETTINGS.get("resumo") or {}).get("lembretes", True):
                self._texts["lembretes"] = self._reminders_text()
                self._draw()
        self._area.after(_REMINDERS_CHECK_MS, self._watch_reminders)

    def _fetch(self):
        now = dt.datetime.now()
        texts = {}
        sources_map = briefing.sources(self._connections, now, SETTINGS.get("resumo") or {}, [])
        for part, source in sources_map.items():
            if part == "lembretes":
                texts[part] = self._reminders_text()
                continue
            try:
                texts[part] = source()
            except Exception as e:           # keeps the last good text; the card does not shout
                log.info("[Today] %s unavailable: %s", part, e)
                if part in self._texts:
                    texts[part] = self._texts[part]
        try:
            self._area.after(0, self._apply, texts)
        except (RuntimeError, tk.TclError):
            pass                             # window closed meanwhile

    def _apply(self, texts: dict[str, str]):
        self._texts = texts
        self._draw()

    @staticmethod
    def _reminders_text() -> str:
        items = reminders.pending_items()
        if not items:
            return "Nenhum lembrete pendente."
        now = dt.datetime.now()
        lines = [reminders.describe(item, now) for item in items[:briefing.MAX_REMINDERS]]
        rest = len(items) - len(lines)
        return "\n".join(lines) + (f"\ne mais {rest}" if rest > 0 else "")

    def _draw(self):
        for card, _ in self._cards.values():
            card.pack_forget()               # repacked in order below
        for part, (card, body) in self._cards.items():
            text = self._texts.get(part, "")
            if text:                         # part off or unavailable: no empty card, no error
                body.config(text=text)
                card.pack(fill=tk.X, pady=(0, theme.px(theme.GAP)))
