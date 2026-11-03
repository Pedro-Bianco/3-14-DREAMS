"""Base tab: knowledge base — chosen documents (PDF, Word, slides, spreadsheets, text) and pasted texts."""

import hashlib
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from pidreams.memory import documents
from pidreams.ui import theme

_FILE_TYPES = [("Documentos", " ".join(f"*{s}" for s in sorted(documents.SUPPORTED))),
               ("PDF", "*.pdf"), ("Word", "*.docx"), ("PowerPoint", "*.pptx"), ("Excel", "*.xlsx"),
               ("Texto", "*.txt *.md *.csv")]
_KIND_NAMES = {"pdf": "PDF", "docx": "Word", "pptx": "slides", "xlsx": "planilha", "csv": "CSV",
               "txt": "texto", "md": "Markdown", "texto": "texto colado"}


class KBPanelMixin:
    """Base tab: knowledge base."""

    def _build_kb_tab(self, parent):
        pad = theme.px(14)
        status_row = tk.Frame(parent, bg=theme.GLASS)
        status_row.pack(fill=tk.X, padx=pad, pady=(pad, theme.px(4)))
        self._kb_dot = tk.Label(status_row, text="●", bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT)
        self._kb_dot.pack(side=tk.LEFT)
        self._kb_status_var = tk.StringVar(value="Verificando…")
        tk.Label(status_row, textvariable=self._kb_status_var, bg=theme.GLASS, fg=theme.TEXT2,
                 font=theme.FONT).pack(side=tk.LEFT, padx=(theme.px(6), 0))
        self._kb_count_var = tk.StringVar(value="")
        tk.Label(status_row, textvariable=self._kb_count_var, bg=theme.GLASS, fg=theme.MUTED,
                 font=theme.FONT_SMALL).pack(side=tk.RIGHT)

        theme.section(parent, "Base de conhecimento").pack(fill=tk.X, padx=pad, pady=(theme.px(8), theme.px(4)))
        tk.Label(parent, text="PDF, Word, slides, planilhas e textos: pergunte sobre eles e eu digo de onde veio.",
                 bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w", justify="left",
                 wraplength=theme.px(260)).pack(fill=tk.X, padx=pad)
        theme.button(parent, "Escolher arquivos", self._kb_choose_files, kind="primary",
                     icon="folder").pack(fill=tk.X, padx=pad, pady=(theme.px(8), theme.px(4)))

        # Pasted text: title + text, saved as one document.
        self._kb_source_var = tk.StringVar()
        title_row = tk.Frame(parent, bg=theme.GLASS)
        title_row.pack(fill=tk.X, padx=pad, pady=(theme.px(6), theme.px(3)))
        title_row.grid_columnconfigure(1, weight=1)
        tk.Label(title_row, text="Ou cole um texto · título", bg=theme.GLASS, fg=theme.TEXT2,
                 font=theme.FONT_SMALL).grid(row=0, column=0, sticky="w", padx=(0, theme.px(8)))
        theme.entry(title_row, textvariable=self._kb_source_var, width=1).grid(row=0, column=1, sticky="ew", ipady=theme.px(3))
        text_frame = tk.Frame(parent, bg=theme.GLASS)
        text_frame.pack(fill=tk.X, padx=pad)
        txt_scroll = ttk.Scrollbar(text_frame, orient="vertical")
        txt_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._kb_text = tk.Text(
            text_frame, height=4, width=1, bg=theme.INPUT, fg=theme.TEXT, insertbackground=theme.CYAN,
            font=theme.FONT_SMALL, relief=tk.FLAT, wrap=tk.WORD, padx=theme.px(8), pady=theme.px(6),
            highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.CYAN,
            yscrollcommand=txt_scroll.set)
        self._kb_text.pack(fill=tk.X)
        txt_scroll.config(command=self._kb_text.yview)
        self._kb_ingest_status = tk.StringVar(value="")
        tk.Label(parent, textvariable=self._kb_ingest_status, bg=theme.GLASS, fg=theme.MUTED,
                 font=theme.FONT_SMALL, anchor="w").pack(fill=tk.X, padx=pad)
        theme.button(parent, "Guardar o texto", self._kb_save_text, icon="add").pack(fill=tk.X, padx=pad)

        self._kb_expanded: set[str] = set()
        theme.section(parent, "Documentos").pack(fill=tk.X, padx=pad, pady=(theme.px(12), theme.px(4)))
        # Clear-all button packed before the list so it stays visible at the bottom.
        theme.button(parent, "Apagar tudo", self._kb_clear_all, kind="danger",
                     icon="delete").pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=pad)

        sources_outer = tk.Frame(parent, bg=theme.GLASS)
        sources_outer.pack(fill=tk.BOTH, expand=True, padx=(pad, theme.px(4)))
        src_scrollbar = ttk.Scrollbar(sources_outer, orient="vertical")
        src_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._kb_canvas = tk.Canvas(sources_outer, bg=theme.INPUT, highlightthickness=0, width=1,
                                    yscrollcommand=src_scrollbar.set)
        self._kb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        src_scrollbar.config(command=self._kb_canvas.yview)

        self._kb_wrap = theme.px(200)
        self._kb_inner = tk.Frame(self._kb_canvas, bg=theme.INPUT)
        self._kb_canvas_window = self._kb_canvas.create_window((0, 0), window=self._kb_inner, anchor="nw")
        self._kb_inner.bind("<Configure>", lambda _: self._kb_canvas.configure(scrollregion=self._kb_canvas.bbox("all")))
        self._kb_canvas.bind("<Configure>", self._kb_on_canvas_resize)
        self._kb_canvas.bind("<MouseWheel>",
            lambda e: self._kb_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        # first refresh triggered by _on_stores_ready

    def _kb_on_canvas_resize(self, event):
        self._kb_canvas.itemconfig(self._kb_canvas_window, width=event.width)
        self._kb_wrap = max(theme.px(120), event.width - theme.px(60))
        stack = list(self._kb_inner.winfo_children())
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if getattr(widget, "_wraps", False):
                widget.config(wraplength=self._kb_wrap)

    # ── saving ───────────────────────────────────────────────────────────────

    def _kb_ready(self) -> bool:
        if self._kb_store is None or not self._kb_store.available:
            self._kb_ingest_status.set("aguarde: a base de conhecimento está carregando…")
            return False
        return True

    def _kb_choose_files(self):
        if not self._kb_ready():
            return
        paths = filedialog.askopenfilenames(parent=self.root, title="Guardar na base de conhecimento",
                                            filetypes=_FILE_TYPES)
        if not paths:
            return
        from pidreams.ui.download_dialog import DownloadDialog

        store = self._kb_store
        # One bar per file; a file the base cannot read shows why on its own bar (documents.Unreadable).
        tasks = [(path.replace("\\", "/").rsplit("/", 1)[-1],
                  lambda progress, cancel, path=path: store.ingest_document(path, progress, cancel))
                 for path in paths]
        DownloadDialog(self.root, "Guardando na base de conhecimento", tasks,
                       on_finish=lambda _ok, _failures: self._kb_refresh())

    def _kb_save_text(self):
        if not self._kb_ready():
            return
        content = self._kb_text.get("1.0", tk.END).strip()
        if not content:
            self._kb_ingest_status.set("cole algum texto antes de guardar")
            return
        source = self._kb_source_var.get().strip() or hashlib.md5(content.encode("utf-8", "replace")).hexdigest()[:8]
        self._kb_ingest_status.set("guardando…")

        def _run():
            n = self._kb_store.ingest(content, source_name=source)

            def _done():
                self._kb_text.delete("1.0", tk.END)
                self._kb_source_var.set("")
                self._kb_ingest_status.set(f"{n} parte(s) guardada(s) em '{source}'")
                self._kb_refresh()
            self.root.after(0, _done)
        threading.Thread(target=_run, daemon=True).start()

    # ── list ─────────────────────────────────────────────────────────────────

    def _kb_refresh(self):
        def _run():
            available = self._kb_store is not None and self._kb_store.available
            docs = self._kb_store.list_documents() if available else []
            expanded = {d: self._kb_store.pieces_of(d) for d in self._kb_expanded} if available else {}
            self.root.after(0, lambda: self._kb_render(available, docs, expanded))
        threading.Thread(target=_run, daemon=True).start()

    def _kb_render(self, available: bool, docs: list[dict], expanded: dict[str, list[dict]]):
        self._kb_dot.config(fg=theme.OK if available else theme.DANGER)
        self._kb_status_var.set("Conectada" if available else "Indisponível")
        self._kb_count_var.set(f"{len(docs)} documento(s)" if available else "")
        for w in self._kb_inner.winfo_children():
            w.destroy()
        if not available or not docs:
            tk.Label(self._kb_inner, text="Base de conhecimento indisponível" if not available
                     else "nenhum documento guardado ainda", bg=theme.INPUT, fg=theme.MUTED,
                     font=theme.FONT_SMALL, padx=8, pady=6).pack(anchor="w")
            return
        for doc in docs:
            self._kb_render_document(doc, expanded.get(doc["doc_id"]))
        self._kb_canvas.yview_moveto(0)

    def _kb_render_document(self, doc: dict, pieces: list[dict] | None):
        hdr = tk.Frame(self._kb_inner, bg=theme.INPUT, cursor="hand2")
        hdr.pack(fill=tk.X, padx=4, pady=(3, 0))
        hdr.grid_columnconfigure(1, weight=1)
        arrow = tk.Label(hdr, text="▼" if pieces is not None else "▶", bg=theme.INPUT, fg=theme.TEXT,
                         font=theme.FONT_SMALL, cursor="hand2")
        arrow.grid(row=0, column=0, sticky="w", padx=(4, 2))
        name = tk.Label(hdr, text=doc["source"], bg=theme.INPUT, fg=theme.TEXT, font=theme.FONT,
                        wraplength=self._kb_wrap, justify="left", anchor="nw", cursor="hand2")
        name._wraps = True
        name.grid(row=0, column=1, sticky="ew", padx=(0, 2))
        tk.Button(hdr, text=theme.ICON["close"], command=lambda d=doc["doc_id"]: self._kb_delete_document(d),
                  bg=theme.INPUT, fg=theme.DANGER, activebackground=theme.DANGER_BG, activeforeground=theme.DANGER,
                  font=theme.FONT_SMALL, relief=tk.FLAT, padx=3, pady=0, cursor="hand2", bd=0
                  ).grid(row=0, column=2, sticky="ne", padx=(0, 2))
        info = tk.Label(hdr, text=f"{_KIND_NAMES.get(doc['kind'], doc['kind'])} · {doc['count']} partes",
                        bg=theme.INPUT, fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w", cursor="hand2")
        info.grid(row=1, column=1, columnspan=2, sticky="w", padx=(0, 2), pady=(0, 2))

        def toggle(d=doc["doc_id"]):
            (self._kb_expanded.discard if d in self._kb_expanded else self._kb_expanded.add)(d)
            self._kb_refresh()
        for widget in (hdr, arrow, name, info):
            widget.bind("<Button-1>", lambda _e, fn=toggle: fn())

        if pieces is not None:
            sub = tk.Frame(self._kb_inner, bg=theme.INPUT, pady=2)
            sub.pack(fill=tk.X, padx=12)
            for piece in pieces[:200]:
                preview = piece["text"][:120].replace("\n", " ") + ("…" if len(piece["text"]) > 120 else "")
                where = f"{piece['where']}: " if piece.get("where") else ""
                line = tk.Label(sub, text=f"• {where}{preview}", bg=theme.INPUT, fg=theme.TEXT2, font=theme.FONT_SMALL,
                                wraplength=self._kb_wrap, justify="left", anchor="nw")
                line._wraps = True
                line.pack(fill=tk.X, pady=1)
        tk.Frame(self._kb_inner, bg=theme.BORDER, height=1).pack(fill=tk.X, padx=4)

    def _kb_delete_document(self, doc_id: str):
        def _run():
            self._kb_store.delete_document(doc_id)
            self.root.after(0, self._kb_refresh)
        threading.Thread(target=_run, daemon=True).start()

    def _kb_clear_all(self):
        if self._kb_store is None:
            return

        def _run():
            self._kb_store.clear()
            self.root.after(0, self._kb_refresh)
        threading.Thread(target=_run, daemon=True).start()

