"""The "Adicionar conexão" window: any local MCP server, without editing files."""

import re
import shlex
import threading
import tkinter as tk
import unicodedata
import webbrowser
from typing import Callable
from pidreams.ui import theme

_LOCAL_ADDRESS = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?(/|$)", re.IGNORECASE)


def make_id(name: str) -> str:
    """Stable id that is safe as a tool name: lowercase letters, digits and "_"."""
    strip_accents = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", strip_accents.lower()).strip("_")


def validate(name: str, command: str, address: str, used: set[str]) -> tuple[str, dict]:
    """Returns (id, fields) or raises ValueError with the message for the person."""
    name = name.strip()
    if not 1 <= len(name) <= 40:
        raise ValueError("Dê um nome de 1 a 40 letras.")
    id_ = make_id(name)
    if not id_:
        raise ValueError("O nome precisa ter letras ou números.")
    if id_ in used:
        raise ValueError("Já existe uma conexão com esse nome.")
    command, address = command.strip(), address.strip()
    if bool(command) == bool(address):
        raise ValueError("Preencha o comando OU o endereço local (só um dos dois).")
    if address:
        if not _LOCAL_ADDRESS.match(address):
            raise ValueError("Só endereços deste computador (http://127.0.0.1… ou http://localhost…).")
        return id_, {"nome": name, "endereco": address, "comando": None, "argumentos": []}
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        raise ValueError("O comando tem aspas sem fechar.") from None
    parts = [p.strip('"') for p in parts]
    return id_, {"nome": name, "comando": parts[0], "argumentos": parts[1:], "endereco": None}


def _dialog(master, title: str) -> tk.Toplevel:
    window = tk.Toplevel(master)
    window.title(title)
    window.configure(bg=theme.GLASS, padx=theme.px(18), pady=theme.px(10))
    return window


def _help(window, text: str, link_text: str = "", url: str = ""):
    help_text = tk.Label(window, text=text, bg=theme.GLASS, fg=theme.TEXT2, font=theme.FONT_SMALL,
                         wraplength=theme.px(480), justify="left", anchor="w")
    help_text.pack(fill=tk.X, pady=(theme.px(4), theme.px(6)))
    if link_text:
        theme.button(window, link_text, lambda: webbrowser.open(url)).pack(anchor="w")


def _field(window, label_text: str, var: tk.StringVar, hidden: bool = False):
    tk.Label(window, text=label_text, bg=theme.GLASS, fg=theme.TEXT, font=theme.FONT_SMALL,
             anchor="w").pack(fill=tk.X, pady=(theme.px(10), theme.px(3)))
    theme.entry(window, textvariable=var, show="•" if hidden else "", width=60).pack(fill=tk.X, ipady=theme.px(4))


def _footer(window, confirm_text: str, confirm) -> tk.Label:
    """Status line (errors, "testing…") + Cancelar / confirm buttons; returns the status line."""
    state = tk.Label(window, text="", bg=theme.GLASS, fg=theme.DANGER, font=theme.FONT_SMALL,
                     wraplength=theme.px(480), justify="left", anchor="w")
    state.pack(fill=tk.X, pady=(theme.px(8), 0))
    footer = tk.Frame(window, bg=theme.GLASS)
    footer.pack(fill=tk.X, pady=(theme.px(12), theme.px(4)))
    theme.button(footer, confirm_text, confirm, kind="primary").pack(side=tk.RIGHT, padx=(theme.px(6), 0))
    theme.button(footer, "Cancelar", window.destroy).pack(side=tk.RIGHT)
    return state


class NewConnection:
    def __init__(self, master, used: set[str], on_save: Callable[[str, dict], None]):
        self._used, self._on_save = used, on_save
        self.window = _dialog(master, "Adicionar conexão MCP")
        self._v = {k: tk.StringVar() for k in ("nome", "comando", "endereco", "descricao")}
        labels = (("nome", "Nome"), ("comando", "Comando que inicia o servidor (com os argumentos)"),
                   ("endereco", "OU endereço local, se o servidor já está rodando"),
                   ("descricao", "Quando o assistente deve usar (opcional; senão vem do servidor)"))
        for key, label_text in labels:
            _field(self.window, label_text, self._v[key])
        self._error = _footer(self.window, "Adicionar e ligar", self._save)

    def _save(self):
        try:
            id_, fields = validate(self._v["nome"].get(), self._v["comando"].get(),
                                  self._v["endereco"].get(), self._used)
        except ValueError as e:
            self._error.config(text=str(e))
            return
        fields["descricao"] = self._v["descricao"].get().strip()[:300]
        self.window.destroy()
        self._on_save(id_, fields)


class CalendarLink:
    """Secret iCal address of Google Calendar; tests it before saving (it goes to the secret store)."""

    def __init__(self, master, on_save: Callable[[str], None]):
        self._on_save = on_save
        self.window = _dialog(master, "Agenda do Google")
        self._url = tk.StringVar()
        _help(self.window, "No Google Agenda (computador): Configurações → em \"Configurações das minhas agendas\" "
                           "clique na sua agenda → \"Integrar agenda\" → copie o \"Endereço secreto no formato "
                           "iCal\". O PI só lê a agenda. Se o link vazar, use \"Redefinir\" no Google e cole o novo.",
              "Abrir as configurações do Google Agenda", "https://calendar.google.com/calendar/r/settings")
        _field(self.window, "Endereço secreto no formato iCal", self._url, hidden=True)
        self._state = _footer(self.window, "Testar e ligar", self._check)

    def _check(self):
        from pidreams.mcp.ical_calendar import check_link

        url = self._url.get().strip()
        self._state.config(text="Lendo a agenda…")

        def check_connection():
            error = check_link(url)
            self.window.after(0, lambda: self._end(error, url))

        threading.Thread(target=check_connection, daemon=True).start()

    def _end(self, error, url):
        if error:
            self._state.config(text=error)
            return
        self.window.destroy()
        self._on_save(url)


class GmailAccount:
    """Address + app password; tests the login before saving (the password goes to the secret store)."""

    def __init__(self, master, current_account: str, on_save: Callable[[str, str], None]):
        self._on_save = on_save
        self.window = _dialog(master, "Gmail")
        self._account, self._password = tk.StringVar(value=current_account), tk.StringVar()
        _help(self.window, "Use uma senha de app do Google (16 letras), não a sua senha normal. Ela exige a "
                           "verificação em duas etapas ligada na conta.",
              "Criar senha de app no Google", "https://myaccount.google.com/apppasswords")
        _field(self.window, "Endereço do Gmail", self._account)
        _field(self.window, "Senha de app", self._password, hidden=True)
        self._state = _footer(self.window, "Testar e ligar", self._check)

    def _check(self):
        from pidreams.mcp.gmail import check_login

        account, password = self._account.get().strip(), self._password.get().replace(" ", "")
        if "@" not in account or len(password) < 16:
            self._state.config(text="Preencha o endereço e a senha de app de 16 letras.")
            return
        self._state.config(text="Testando o login no Gmail…")

        def check_connection():
            error = check_login(account, password)
            self.window.after(0, lambda: self._end(error, account, password))

        threading.Thread(target=check_connection, daemon=True).start()

    def _end(self, error, account, password):
        if error:
            self._state.config(text=error)
            return
        self.window.destroy()
        self._on_save(account, password)
