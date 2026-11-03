"""Serviços tab: turns services and connections on and off."""

import tkinter as tk
import threading
from pidreams.ui import theme


class ServicesPanelMixin:
    """Serviços tab: turns services and connections on and off."""

    # ── Services tab (turns agent capabilities on and off) ───────────────────

    def _build_services_tab(self, parent):
        pad = theme.px(14)
        theme.section(parent, "Serviços").pack(fill=tk.X, padx=pad, pady=(pad, theme.px(4)))

        # The camera has its own button next to Mudo (center panel).
        for name in ("memory",):
            svc = self._services.get(name)
            row = tk.Frame(parent, bg=theme.GLASS)
            row.pack(fill=tk.X, padx=pad, pady=(theme.px(6), 0))
            tk.Label(row, text=svc.label, bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT).pack(side=tk.LEFT)
            btn = theme.button(row, "Desligar" if svc.running else "Ligar",
                               lambda n=name: self._on_service_toggle(n))
            btn.pack(side=tk.RIGHT)
            status = tk.Label(parent, text="desligado", bg=theme.GLASS, fg=theme.MUTED,
                              font=theme.FONT_SMALL, anchor="w", justify="left")
            status.pack(fill=tk.X, padx=pad, pady=(theme.px(2), theme.px(8)))
            status.bind("<Configure>", lambda e, s=status: s.config(wraplength=max(1, e.width)))
            self._svc_rows[name] = {"btn": btn, "status": status}

        tk.Frame(parent, bg=theme.BORDER, height=1).pack(fill=tk.X)
        self._build_connections(parent)

        theme.section(parent, "Registro").pack(fill=tk.X, padx=pad, pady=(theme.px(10), theme.px(4)))
        self._svc_log = tk.Text(
            parent, height=8, width=1, bg=theme.INPUT, fg=theme.TEXT2,
            font=theme.FONT_CODE, relief=tk.FLAT, wrap="word", padx=theme.px(8), pady=theme.px(6),
            insertbackground=theme.TEXT2, highlightthickness=0,
        )
        self._svc_log.pack(fill=tk.BOTH, expand=True, padx=pad, pady=(0, pad))
        self._svc_log.config(state=tk.DISABLED)

    def _on_service_log(self, name: str, msg: str):
        """Called from service threads — hands it back to the Tk thread."""
        def _append():
            if self._svc_log is None:
                return
            self._svc_log.config(state=tk.NORMAL)
            self._svc_log.insert(tk.END, f"[{name}] {msg}\n")
            self._svc_log.see(tk.END)
            self._svc_log.config(state=tk.DISABLED)
        try:
            self.root.after(0, _append)
        except RuntimeError:
            pass

    def _on_service_toggle(self, name: str):
        svc = self._services.get(name)
        start_connection = not svc.running
        row = self._svc_rows[name]
        row["btn"].config(state=tk.DISABLED, text="…")

        def _work():
            try:
                msg = self._services.toggle(name, start_connection)
                self._on_service_log(name, msg)
            except RuntimeError as e:
                self._on_service_log(name, f"não foi possível ligar: {e}")
            except Exception as e:
                self._on_service_log(name, f"erro inesperado: {e!r}")
            self.root.after(0, self._refresh_services)

        threading.Thread(target=_work, daemon=True).start()

    def _tick_services(self):
        """A service may change from another thread; without this the panel would show
        the state frozen at the moment the tab was opened."""
        try:
            if self._svc_visible:
                signature = tuple(svc.running for svc in self._services.services.values())
                if signature != self._svc_signature:
                    self._svc_signature = signature
                    self._refresh_services()
        except Exception:
            pass
        self.root.after(1200, self._tick_services)

    def _refresh_services(self):
        for name, row in self._svc_rows.items():
            svc = self._services.get(name)
            row["btn"].config(state=tk.NORMAL, text="Desligar" if svc.running else "Ligar")
            theme.set_kind(row["btn"], "danger" if svc.running else "normal")
            row["status"].config(
                text=svc.status(),
                fg=theme.VIOLET if svc.running else theme.MUTED,
            )
