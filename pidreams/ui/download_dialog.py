"""Model download window: one bar per item, the failure reason and Cancel.

Used at install time (PIDreams.exe --setup-models) and when an optional feature
needs a new model (camera). The app stays usable while it downloads.
"""

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from pidreams.hardware.models import Cancelled, DownloadFailed
from pidreams.ui import theme

Task = tuple[str, Callable]       # (label, function(progress, cancel))


class DownloadDialog:
    def __init__(self, master: tk.Misc | None, title: str, tasks: list[Task],
                 on_finish: Callable[[bool, list[str]], None] | None = None):
        self.window = tk.Toplevel(master) if master is not None else tk.Tk()
        if master is None:
            theme.init(self.window)          # own window (installer): needs the ttk styles too
        self.window.title(title)
        self.window.configure(bg=theme.GLASS)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._cancel = threading.Event()
        self._on_finish = on_finish
        self.ok = False
        self.failures: list[str] = []

        tk.Label(self.window, text=title, bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_SECTION).pack(
            pady=(theme.px(16), theme.px(6)))
        self._lines = []
        for label_text, _ in tasks:
            frame = tk.Frame(self.window, bg=theme.GLASS)
            frame.pack(fill=tk.X, padx=theme.px(22), pady=theme.px(5))
            tk.Label(frame, text=label_text, bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT, anchor="w").pack(fill=tk.X)
            bar = ttk.Progressbar(frame, maximum=100, length=theme.px(440))
            bar.pack(fill=tk.X)
            state = tk.Label(frame, text="aguardando", bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                              anchor="w", justify="left", wraplength=theme.px(440))
            state.pack(fill=tk.X)
            self._lines.append((bar, state))
        self._button = theme.button(self.window, "Cancelar", self.cancel)
        self._button.pack(pady=theme.px(14))
        threading.Thread(target=self._execute, args=(tasks,), daemon=True).start()

    def _on_screen(self, function, *args):
        try:
            self.window.after(0, function, *args)
        except (RuntimeError, tk.TclError):
            pass                      # window already closed

    def _execute(self, tasks: list[Task]):
        for i, (label_text, function) in enumerate(tasks):
            bar, state = self._lines[i]

            def progress(pct, text, bar=bar, state=state):
                self._on_screen(lambda: (bar.configure(value=pct), state.configure(text=text)))
            try:
                function(progress, self._cancel)
            except Cancelled:
                self.failures.append(f"{label_text}: cancelado")
                break
            except DownloadFailed as e:
                self.failures.append(f"{label_text}: {e}")
                self._on_screen(lambda e=e, state=state: state.configure(text=str(e), fg=theme.DANGER))
            except Exception as e:     # noqa: BLE001 — never leave the window stuck
                self.failures.append(f"{label_text}: {e}")
                self._on_screen(lambda e=e, state=state: state.configure(text=str(e), fg=theme.DANGER))
        self.ok = not self.failures
        self._on_screen(self._end)

    def _end(self):
        if self.ok:
            self.window.destroy()
        else:
            self._button.configure(text="Fechar", command=self.window.destroy)
        self._notify()

    def _notify(self):
        if self._on_finish:
            notice, self._on_finish = self._on_finish, None     # only once
            notice(self.ok, [] if self.ok else (self.failures or ["cancelado"]))

    def cancel(self):
        self._cancel.set()
        self.ok = False
        self._notify()
        self.window.destroy()
