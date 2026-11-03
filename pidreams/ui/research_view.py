"""The deep-research screen: the topic, the steps, the sources as they are read and, at the end, the
report with buttons to cancel, close and open the saved file."""

import os
import tkinter as tk

from pidreams.ui import theme

_STEPS = [("esclarecendo", "Entender o que você quer"), ("planejando", "Planejar as perguntas"), ("buscando", "Buscar fontes"), ("lendo", "Ler as fontes"),
          ("escrevendo", "Escrever o relatório"), ("guardando", "Guardar na Base")]
_ORDER = [s for s, _ in _STEPS]
HINT = ("Peça um tema, por exemplo: \"pesquisa a fundo sobre baterias de sódio\". Leva de 1 a 3 minutos; "
        "o relatório fica guardado na Base. Diga \"cancelar pesquisa\" para parar ou \"fechar pesquisa\" para voltar.")
CREDITS = "Fontes: Wikipédia (CC BY-SA) · Google Notícias · DuckDuckGo quando disponível"


class ResearchView(tk.Frame):
    def __init__(self, parent, on_close, on_cancel, on_answer=lambda picks: None):
        """on_answer(picks): the user's choice per clarifying question ("" = no preference)."""
        super().__init__(parent, bg=theme.BG)
        self._file = ""
        self._on_answer = on_answer
        self._shown_choices = None
        bar = tk.Frame(self, bg=theme.GLASS)
        bar.pack(fill=tk.X)
        tk.Label(bar, text=f"{theme.ICON['search']}  Pesquisa profunda", bg=theme.GLASS, fg=theme.TEXT,
                 font=theme.FONT_SECTION).pack(side=tk.LEFT, padx=theme.px(12), pady=theme.px(8))
        theme.button(bar, "Fechar", on_close, icon="close", font=theme.FONT_SMALL).pack(side=tk.RIGHT, padx=theme.px(8))
        self._cancel = theme.button(bar, "Cancelar", on_cancel, kind="danger", font=theme.FONT_SMALL)

        self._topic = tk.Label(self, text="", bg=theme.BG, fg=theme.CYAN, font=theme.FONT_SECTION, anchor="w",
                               justify="left")
        self._topic.pack(fill=tk.X, padx=theme.px(14), pady=(theme.px(10), 0))
        steps = tk.Frame(self, bg=theme.BG)
        steps.pack(fill=tk.X, padx=theme.px(14), pady=theme.px(6))
        self._step_labels = {}
        for key, text in _STEPS:
            label = tk.Label(steps, text=f"○  {text}", bg=theme.BG, fg=theme.MUTED, font=theme.FONT, anchor="w")
            label.pack(fill=tk.X)
            self._step_labels[key] = (label, text)

        # Clarifying questions as option buttons (shown only while the research waits for them).
        self._choices = tk.Frame(self, bg=theme.GLASS_HI, highlightthickness=1, highlightbackground=theme.BORDER)
        box = tk.Frame(self, bg=theme.INPUT)
        box.pack(fill=tk.BOTH, expand=True, padx=theme.px(14), pady=(theme.px(4), theme.px(8)))
        self._box = box
        scroll = tk.Scrollbar(box)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text = tk.Text(box, bg=theme.INPUT, fg=theme.TEXT, font=theme.FONT, wrap="word", relief=tk.FLAT,
                             padx=theme.px(10), pady=theme.px(8), yscrollcommand=scroll.set, width=1, height=1)
        self._text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self._text.yview)
        self._text.tag_configure("h", foreground=theme.CYAN, font=theme.FONT_BOLD)
        self._text.tag_configure("muted", foreground=theme.MUTED)

        foot = tk.Frame(self, bg=theme.GLASS)
        foot.pack(fill=tk.X)
        self._open = theme.button(foot, "Abrir relatório", self._open_file, font=theme.FONT_SMALL)
        self._status = tk.StringVar(value="")
        tk.Label(foot, textvariable=self._status, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                 anchor="w").pack(side=tk.LEFT, padx=theme.px(12), pady=theme.px(6))
        tk.Label(foot, text=CREDITS, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL).pack(side=tk.RIGHT, padx=theme.px(12))
        self.reset()

    def _show_choices(self, choices: list[dict]) -> None:
        if choices == self._shown_choices:
            return
        self._shown_choices = choices
        for w in self._choices.winfo_children():
            w.destroy()
        if not choices:
            self._choices.pack_forget()
            return
        tk.Label(self._choices, text="Antes de pesquisar, escolha (ou responda por voz):", bg=theme.GLASS_HI,
                 fg=theme.TEXT, font=theme.FONT_BOLD, anchor="w").pack(fill=tk.X, padx=theme.px(10), pady=(theme.px(8), 0))
        picks = [tk.StringVar(value="") for _ in choices]
        for c, var in zip(choices, picks):
            tk.Label(self._choices, text=c["question"], bg=theme.GLASS_HI, fg=theme.TEXT2, font=theme.FONT,
                     anchor="w", justify="left").pack(fill=tk.X, padx=theme.px(10), pady=(theme.px(6), theme.px(2)))
            row = tk.Frame(self._choices, bg=theme.GLASS_HI)
            row.pack(fill=tk.X, padx=theme.px(10))
            buttons = []
            for option in c["options"]:
                b = theme.button(row, option, None, font=theme.FONT_SMALL)
                b.config(command=lambda v=var, o=option, bs=buttons, me=b: (
                    v.set(o), [theme.set_kind(x, "on" if x is me else "normal") for x in bs]))
                b.pack(side=tk.LEFT, padx=(0, theme.px(4)), pady=theme.px(2))
                buttons.append(b)
        actions = tk.Frame(self._choices, bg=theme.GLASS_HI)
        actions.pack(fill=tk.X, padx=theme.px(10), pady=theme.px(8))
        theme.button(actions, "Pesquisar", lambda: self._answer([v.get() for v in picks]), kind="primary",
                     icon="search", font=theme.FONT_SMALL).pack(side=tk.LEFT)
        theme.button(actions, "Pular", lambda: self._answer([""] * len(picks)),
                     font=theme.FONT_SMALL).pack(side=tk.LEFT, padx=theme.px(6))
        self._choices.pack(fill=tk.X, padx=theme.px(14), pady=(theme.px(4), 0), before=self._box)

    def _answer(self, picks: list[str]) -> None:
        self._show_choices([])
        self._on_answer(picks)

    def reset(self) -> None:
        self._show_choices([])
        self._topic.config(text="")
        self._set_text([(HINT, "muted")])
        self._paint_steps(None)
        self._status.set("")
        self._cancel.pack_forget()
        self._open.pack_forget()

    def _set_text(self, parts) -> None:
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        for text, tag in parts:
            self._text.insert(tk.END, text, tag)
        self._text.config(state=tk.DISABLED)

    def _paint_steps(self, current: str | None, finished: bool = False) -> None:
        index = _ORDER.index(current) if current in _ORDER else (len(_ORDER) if finished else -1)
        for i, key in enumerate(_ORDER):
            label, text = self._step_labels[key]
            if i < index:
                label.config(text=f"●  {text}", fg=theme.OK)
            elif i == index:
                label.config(text=f"◉  {text}…", fg=theme.CYAN)
            else:
                label.config(text=f"○  {text}", fg=theme.MUTED)

    def progress(self, s: dict) -> None:
        """research_progress event."""
        step = s["etapa"]
        self._topic.config(text=s["tema"])
        self._show_choices(s.get("escolhas") or [])
        if step in _ORDER:
            self._paint_steps(step)
            self._cancel.pack(side=tk.RIGHT, padx=theme.px(4))
            self._open.pack_forget()
            parts = []
            if s["perguntas"]:
                parts.append(("Perguntas\n", "h"))
                parts += [(f"• {q}\n", "") for q in s["perguntas"]]
            if s["fontes"]:
                parts.append(("\nFontes\n", "h"))
                for f in s["fontes"]:
                    mark = "✓" if f["ok"] else ("✗" if f["ok"] is False else "·")
                    parts.append((f"{mark} {f['title']}\n", "" if f["ok"] else "muted"))
            self._set_text(parts or [("Planejando…", "muted")])
            self._status.set(f"{s['fontes_lidas']} de {s['fontes_total']} fontes lidas · {s['segundos']} s")
            return
        self._cancel.pack_forget()
        if step == "pronta":
            self._paint_steps(None, finished=True)
            self._file = s.get("arquivo", "")
            if self._file:
                self._open.pack(side=tk.RIGHT, padx=theme.px(8))
                with open(self._file, encoding="utf-8") as f:
                    report = f.read()
                self._set_text(_markdown(report))
                self._status.set(f"Pronta em {s['segundos']} s · guardada na Base")
            else:
                self._set_text([(s.get("resumo") or "Não encontrei material suficiente.", "")])
                self._status.set("Sem relatório")
        elif step == "cancelada":
            self._paint_steps(None)
            self._status.set("Pesquisa cancelada")
        elif step == "falhou":
            self._paint_steps(None)
            self._status.set("A pesquisa falhou")

    def _open_file(self) -> None:
        if self._file and os.path.isfile(self._file):
            os.startfile(self._file)


def _markdown(report: str) -> list[tuple[str, str]]:
    """Headings highlighted; the rest as it is."""
    parts = []
    for line in report.splitlines(keepends=True):
        if line.startswith("#"):
            parts.append((line.lstrip("# "), "h"))
        elif line.startswith("_") and line.strip().endswith("_"):
            parts.append((line.strip("_\n") + "\n", "muted"))
        else:
            parts.append((line, ""))
    return parts
