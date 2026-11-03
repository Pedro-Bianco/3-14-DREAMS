"""Notice bar at the top of the window: a message + up to two action buttons.

One notice per code ("ollama", "model", "chat", "microphone", "camera"); the
latest one shows. It disappears by itself when the last notice is resolved.
"""

import tkinter as tk
from typing import Callable

from pidreams.ui import theme

# level → (background, text, icon)
_LEVELS = {"error": (theme.DANGER_BG, theme.DANGER, "error"),
           "warning": (theme.WARN_BG, theme.WARN, "warning")}


class NoticeBar(tk.Frame):
    def __init__(self, master, execute: Callable[[str, dict], None]):
        super().__init__(master)
        self._execute = execute            # (action, notice) -> None
        self._notices: dict[str, dict] = {}
        self._edge = tk.Frame(self, width=theme.px(4))
        self._edge.pack(side=tk.LEFT, fill=tk.Y)
        self._icon = tk.Label(self, font=theme.FONT, padx=theme.px(10))
        self._icon.pack(side=tk.LEFT)
        self._buttons = tk.Frame(self)
        self._buttons.pack(side=tk.RIGHT, padx=theme.px(8))
        # Wraps instead of cutting when the window is narrow.
        self._text = tk.Label(self, anchor="w", justify="left", font=theme.FONT, pady=theme.px(7))
        self._text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._text.bind("<Configure>", lambda e: self._text.config(wraplength=max(1, e.width - theme.px(8))))

    def show(self, notice: dict) -> None:
        self._notices.pop(notice["code"], None)
        self._notices[notice["code"]] = notice   # the latest one goes last
        self._draw()

    def resolve(self, code: str) -> None:
        if self._notices.pop(code, None) is not None:
            self._draw()

    def current(self) -> dict | None:
        return next(reversed(self._notices.values()), None)

    def _draw(self) -> None:
        notice = self.current()
        if notice is None:
            self.grid_remove()
            return
        background, front, icon = _LEVELS.get(notice.get("level", "error"), _LEVELS["error"])
        for w in (self, self._buttons):
            w.configure(bg=background)
        self._edge.configure(bg=front)
        self._icon.configure(text=theme.ICON[icon], bg=background, fg=front)
        self._text.configure(text=notice["msg"], bg=background, fg=front)
        for b in self._buttons.winfo_children():
            b.destroy()
        for label_text, action in notice.get("actions", [])[:2]:
            tk.Button(self._buttons, text=label_text, font=theme.FONT_SMALL, relief=tk.FLAT, bd=0,
                      bg=front, fg=background, activebackground=theme.TEXT, activeforeground=background,
                      padx=theme.px(10), pady=theme.px(2), cursor="hand2",
                      command=lambda a=action, av=notice: self._execute(a, av)).pack(side=tk.LEFT, padx=theme.px(4))
        tk.Button(self._buttons, text=theme.ICON["close"], font=theme.FONT_SMALL, relief=tk.FLAT, bd=0,
                  bg=background, fg=front, activebackground=background, activeforeground=theme.TEXT,
                  cursor="hand2", command=lambda c=notice["code"]: self.resolve(c)).pack(side=tk.LEFT)
        self.grid()
