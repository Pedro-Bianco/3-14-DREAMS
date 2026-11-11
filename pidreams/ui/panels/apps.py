"""Apps tab: applications the agent may open."""

import tkinter as tk
from tkinter import ttk
from pidreams.agent import tools
from pidreams.core.settings import SETTINGS
from pidreams.ui import theme


class AppsPanelMixin:
    """Apps tab: applications the agent may open."""

    def _build_apps_tab(self, parent):
        pad = theme.px(14)
        theme.section(parent, "Apps permitidos").pack(fill=tk.X, padx=pad, pady=(pad, theme.px(4)))

        self._apps_enabled_var = tk.BooleanVar(value=self._apps_config.get("enabled", False))
        theme.check(parent, "Só abrir os apps marcados", self._apps_enabled_var,
                    self._on_apps_toggle).pack(fill=tk.X, padx=pad, pady=(0, theme.px(6)))
        tk.Frame(parent, bg=theme.BORDER, height=1).pack(fill=tk.X)

        # Add custom app row (packed before the list so it stays visible at the bottom)
        add_frame = tk.Frame(parent, bg=theme.GLASS)
        add_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=pad)
        add_frame.grid_columnconfigure(0, weight=1)
        self._new_app_var = tk.StringVar()
        new_app = theme.entry(add_frame, textvariable=self._new_app_var, width=1)
        new_app.grid(row=0, column=0, sticky="ew", ipady=theme.px(5), padx=(0, theme.px(6)))
        new_app.bind("<Return>", lambda _e: self._add_custom_app())
        theme.button(add_frame, "Adicionar", self._add_custom_app, icon="add").grid(row=0, column=1, sticky="ns")
        tk.Frame(parent, bg=theme.BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)

        # Scrollable checkboxes
        list_outer = theme.keep_solid(tk.Frame(parent, bg=theme.GLASS))   # scrolled: solid on the glass
        list_outer.pack(fill=tk.BOTH, expand=True, padx=(pad, theme.px(4)), pady=theme.px(6))
        scrollbar = ttk.Scrollbar(list_outer, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas = tk.Canvas(list_outer, bg=theme.GLASS, highlightthickness=0, width=1,
                           yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=canvas.yview)

        self._apps_inner_frame = tk.Frame(canvas, bg=theme.GLASS)
        canvas.create_window((0, 0), window=self._apps_inner_frame, anchor="nw")
        self._apps_inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        apps_state = self._apps_config.get("apps", {})
        default_keys = {k for k, _, _ in self._DEFAULT_APPS}
        for app_key, display_name, default_on in self._DEFAULT_APPS:
            self._add_app_row(app_key, display_name, apps_state.get(app_key, default_on))
        # Custom apps saved in config but not in DEFAULT_APPS
        for app_key, enabled in apps_state.items():
            if app_key not in default_keys:
                self._add_app_row(app_key, app_key, enabled)

    def _add_app_row(self, key: str, text: str, enabled: bool):
        var = tk.BooleanVar(value=enabled)
        self._app_vars[key] = var
        theme.check(self._apps_inner_frame, text, var, self._save_allowed_apps).pack(fill=tk.X, pady=1)

    # ── Apps permission helpers ────────────────────────────────────────────────

    def _load_apps_config(self) -> dict:
        return {"enabled": SETTINGS.get("apps.restrict"), "apps": dict(SETTINGS.get("apps.items"))}

    def _save_allowed_apps(self):
        config = {
            "enabled": self._apps_enabled_var.get() if self._apps_enabled_var else False,
            "apps": {k: v.get() for k, v in self._app_vars.items()},
        }
        SETTINGS.set("apps.restrict", config["enabled"])
        SETTINGS.set("apps.items", config["apps"])
        SETTINGS.save()
        self._apply_allowed_apps(config)

    def _apply_allowed_apps(self, config: dict):
        if config.get("enabled", False):
            allowed = {k for k, v in config.get("apps", {}).items() if v}
            tools.set_allowed_apps(allowed)
        else:
            tools.set_allowed_apps(None)

    def _on_apps_toggle(self):
        self._save_allowed_apps()

    def _add_custom_app(self):
        if not self._new_app_var or not self._apps_inner_frame:
            return
        name = self._new_app_var.get().strip().lower().replace(".exe", "")
        if not name or name in self._app_vars:
            self._new_app_var.set("")
            return
        self._add_app_row(name, name, True)
        self._new_app_var.set("")
        self._save_allowed_apps()
