"""MCP connections in the panel: turn servers on and off, see their state and
allow the folders the files server may use."""

import tkinter as tk
from tkinter import filedialog

from pidreams.core.settings import SETTINGS
from pidreams.mcp import builtin, runtime
from pidreams.ui import theme

_STATE = {"conectado": ("● conectado", theme.OK), "iniciando": ("… iniciando", theme.WARN),
           "erro": ("● erro", theme.DANGER), "desligado": ("desligado", None)}


class ConnectionsPanelMixin:
    def _build_connections(self, parent):
        theme.section(parent, "Conexões").pack(fill=tk.X, padx=theme.px(14), pady=(theme.px(10), 0))
        self._connections_frame = tk.Frame(parent, bg=theme.GLASS)
        self._connections_frame.pack(fill=tk.X, padx=theme.px(14))
        self._refresh_connections()

    def _servers_config(self) -> dict:
        return dict(SETTINGS.get("mcp.servers") or {})

    def _refresh_connections(self, _id=None):
        frame = getattr(self, "_connections_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        config = self._servers_config()
        for id_ in [*builtin.BUILTINS, *(i for i in config if i not in builtin.BUILTINS)]:
            name = builtin.BUILTINS[id_].name if id_ in builtin.BUILTINS else config[id_].get("nome", id_)
            state, reason_text = self._connections.state(id_)
            enabled = state in ("conectado", "iniciando")
            line = tk.Frame(frame, bg=theme.GLASS)
            line.pack(fill=tk.X, pady=(theme.px(8), 0))
            tk.Label(line, text=name, bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT).pack(side=tk.LEFT)
            text, color = _STATE[state]
            tk.Label(line, text=text, bg=theme.GLASS, fg=color or theme.MUTED,
                     font=theme.FONT_SMALL).pack(side=tk.LEFT, padx=theme.px(8))
            if id_ not in builtin.BUILTINS:              # built-ins can only be turned off
                self._connection_button(line, theme.ICON["delete"], lambda i=id_: self._remove_connection(i)).pack(side=tk.RIGHT, padx=(4, 0))
            self._connection_button(line, "Desligar" if enabled else "Ligar",
                                lambda i=id_: self._toggle_connection(i)).pack(side=tk.RIGHT)
            if state == "conectado":
                self._connection_button(line, "Ferramentas", lambda i=id_, n=name: self._show_tools(i, n)
                                    ).pack(side=tk.RIGHT, padx=(0, 4))
            if state == "erro" and reason_text:
                reason = tk.Label(frame, text=reason_text, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                                  anchor="w", justify="left")
                reason.pack(fill=tk.X, padx=theme.px(4))
                reason.bind("<Configure>", lambda e, r=reason: r.config(wraplength=max(1, e.width)))
            if id_ == "arquivos":
                self._folder_lines(frame)
            if id_ == "agenda":
                link_line = tk.Frame(frame, bg=theme.GLASS)
                link_line.pack(fill=tk.X, padx=(12, 0))
                tk.Label(link_line, text="só leitura, pelo link secreto", bg=theme.GLASS, fg=theme.TEXT2,
                         font=theme.FONT_SMALL, anchor="w").pack(side=tk.LEFT)
                self._connection_button(link_line, "Trocar link", self._configure_calendar).pack(side=tk.RIGHT)
            if id_ == "gmail":
                account = config.get("gmail", {}).get("conta", "")
                account_line = tk.Frame(frame, bg=theme.GLASS)
                account_line.pack(fill=tk.X, padx=(12, 0))
                tk.Label(account_line, text=account or "conta não informada", bg=theme.GLASS, fg=theme.TEXT2,
                         font=theme.FONT_SMALL, anchor="w").pack(side=tk.LEFT)
                self._connection_button(account_line, "Trocar conta", self._configure_gmail).pack(side=tk.RIGHT)
        theme.button(frame, "Adicionar conexão", self._add_connection, icon="add").pack(anchor="w", pady=(theme.px(10), theme.px(6)))

    def _folder_lines(self, frame):
        for folder in SETTINGS.get("mcp.pastas") or []:
            line = tk.Frame(frame, bg=theme.GLASS)
            line.pack(fill=tk.X, padx=(12, 0))
            tk.Label(line, text=folder, bg=theme.GLASS, fg=theme.TEXT2, font=theme.FONT_SMALL,
                     anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._connection_button(line, theme.ICON["delete"], lambda p=folder: self._change_folders(remove=p)).pack(side=tk.RIGHT)
        self._connection_button(frame, f"{theme.ICON['add']}  Liberar pasta", lambda: self._change_folders(
            add=filedialog.askdirectory(parent=self.root, title="Pasta que o PI dreams pode usar"))
                            ).pack(anchor="w", padx=theme.px(12), pady=(theme.px(2), theme.px(4)))

    def _connection_button(self, parent, text, command):
        b = theme.button(parent, text, command, font=theme.FONT_SMALL)
        b.config(padx=theme.px(8), pady=theme.px(2))
        return b

    # ── actions ──────────────────────────────────────────────────────────────

    def _save_server(self, id_: str, fields: dict):
        """fields are stored as-is in settings.json, so their keys keep the saved format."""
        config = self._servers_config()
        config[id_] = {**config.get(id_, {}), **fields}
        SETTINGS.set("mcp.servers", config)
        SETTINGS.save()

    def _toggle_connection(self, id_: str):
        if (id_ == "gmail" and self._connections.state(id_)[0] == "desligado"
                and not self._servers_config().get("gmail", {}).get("conta")):
            self._configure_gmail()                    # turning on without an account: ask for it first
            return
        if id_ == "agenda" and self._connections.state(id_)[0] == "desligado":
            from pidreams.core import secrets

            if not secrets.get("mcp.agenda.url"):
                self._configure_calendar()               # turning on without a link: ask for it first
                return
        if self._connections.state(id_)[0] in ("conectado", "iniciando"):
            self._save_server(id_, {"ligado": False})
            self._connections.stop_connection(id_)
        else:
            self._save_server(id_, {"ligado": True})
            self._start_connection(id_)
        self._refresh_connections()

    def _start_connection(self, id_: str):
        """Also used when the app opens and by the notice's TENTAR DE NOVO button."""
        if builtin.needs_install(id_):
            from pidreams.ui.download_dialog import DownloadDialog

            DownloadDialog(self.root, "Preparando as conexões (só na primeira vez)",
                           [(f"Node {runtime.NODE_VERSION} e servidores", runtime.install)],
                           on_finish=lambda ok, _f: ok and self._start_connection(id_))
            return
        try:
            arguments = builtin.launch_params(id_, self._servers_config().get(id_, {}),
                                              list(SETTINGS.get("mcp.pastas") or []))
        except (ValueError, KeyError) as e:
            from pidreams.agent import problems

            self._notices.show(problems.problem(f"mcp_{id_}", str(e), [], level="warning"))
            self._save_server(id_, {"ligado": False})
            self._refresh_connections()
            return
        self._connections.start_connection(id_, **arguments)

    def _change_folders(self, add: str = "", remove: str = ""):
        folders = [p for p in SETTINGS.get("mcp.pastas") or [] if p != remove]
        if add and add not in folders:
            folders.append(add.replace("/", "\\"))
        SETTINGS.set("mcp.pastas", folders)
        SETTINGS.save()
        # Folders are server arguments: if it is on, restart it with the new list.
        if self._connections.state("arquivos")[0] in ("conectado", "iniciando"):
            self._start_connection("arquivos")
        self._refresh_connections()

    def _remove_connection(self, id_: str):
        self._connections.stop_connection(id_)
        config = self._servers_config()
        config.pop(id_, None)
        SETTINGS.set("mcp.servers", config)
        SETTINGS.save()
        self._refresh_connections()

    def _show_tools(self, id_: str, name: str):
        window = tk.Toplevel(self.root)
        window.title(f"{name} — ferramentas")
        window.configure(bg=theme.GLASS)
        text = tk.Text(window, width=70, height=22, bg=theme.INPUT, fg=theme.TEXT, font=theme.FONT_SMALL,
                       relief=tk.FLAT, wrap="word", padx=theme.px(10), pady=theme.px(8), highlightthickness=0)
        text.pack(fill=tk.BOTH, expand=True, padx=theme.px(12), pady=theme.px(12))
        offered = {f.name for f in self._connections.tools(id_)}
        for f in self._connections.tools(id_, all_items=True):
            marker = "lê" if f.read_only else "ALTERA (pede confirmação)"
            briefing = f.description.splitlines()[0][:160] if f.description else ""
            outside = "" if f.name in offered else " — não oferecida"
            text.insert(tk.END, f"{f.name} — {marker}{outside}\n   {briefing}\n\n")
        text.config(state=tk.DISABLED)

    def _add_connection(self):
        from pidreams.ui.panels.new_connection import NewConnection

        NewConnection(self.root, set(self._servers_config()) | set(builtin.BUILTINS), self._save_new)

    def _save_new(self, id_: str, fields: dict):
        self._save_server(id_, {**fields, "ligado": True})
        self._start_connection(id_)
        self._refresh_connections()

    def _configure_calendar(self):
        from pidreams.ui.panels.new_connection import CalendarLink

        CalendarLink(self.root, self._save_calendar)

    def _save_calendar(self, url: str):
        from pidreams.core import secrets

        secrets.set("mcp.agenda.url", url)              # whoever has the link reads the calendar: secret store
        self._save_server("agenda", {"ligado": True})
        self._start_connection("agenda")
        self._refresh_connections()

    def _configure_gmail(self):
        from pidreams.ui.panels.new_connection import GmailAccount

        GmailAccount(self.root, self._servers_config().get("gmail", {}).get("conta", ""),
                   self._save_gmail)

    def _save_gmail(self, account: str, password: str):
        from pidreams.core import secrets

        secrets.set("mcp.gmail.senha_app", password)       # nunca no settings.json
        self._save_server("gmail", {"conta": account, "ligado": True})
        self._start_connection("gmail")
        self._refresh_connections()

    def _restart_saved_connections(self):
        for id_, cfg in self._servers_config().items():
            if cfg.get("ligado"):
                self._start_connection(id_)
