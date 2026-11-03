"""Memória tab (long-term memory as a list) and the memory map under the appearance."""

import tkinter as tk
from tkinter import messagebox, ttk
import threading
import datetime
from pidreams.core.settings import SETTINGS
from pidreams.memory import graph as memory_graph
from pidreams.ui import memory_flow, theme
from pidreams.ui.memory_graph import MemoryGraphView

_EMPTY_USE = {"profile": [], "memories": [], "pieces": []}


class MemoryPanelMixin:
    """MEM tab: long-term memory (Qdrant)."""

    # ── LTM memory tab ─────────────────────────────────────────────────────────

    def _build_memory_tab(self, parent):
        pad = theme.px(14)
        status_row = tk.Frame(parent, bg=theme.GLASS)
        status_row.pack(fill=tk.X, padx=pad, pady=(pad, theme.px(6)))
        self._mem_dot = tk.Label(status_row, text="●", bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT)
        self._mem_dot.pack(side=tk.LEFT)
        self._mem_status_var = tk.StringVar(value="Verificando…")
        tk.Label(status_row, textvariable=self._mem_status_var, bg=theme.GLASS, fg=theme.TEXT2,
                 font=theme.FONT).pack(side=tk.LEFT, padx=(theme.px(6), 0))
        theme.button(status_row, "Como funciona", lambda: memory_flow.show(self.root),
                     font=theme.FONT_SMALL).pack(side=tk.RIGHT)
        self._mem_count_var = tk.StringVar(value="")
        tk.Label(status_row, textvariable=self._mem_count_var, bg=theme.GLASS, fg=theme.MUTED,
                 font=theme.FONT_SMALL).pack(side=tk.RIGHT, padx=(0, theme.px(8)))

        def field_row(title, var, on_enter, button_text, command, icon):
            theme.section(parent, title).pack(fill=tk.X, padx=pad, pady=(theme.px(10), theme.px(4)))
            row = tk.Frame(parent, bg=theme.GLASS)
            row.pack(fill=tk.X, padx=pad)
            row.grid_columnconfigure(0, weight=1)
            entry = theme.entry(row, textvariable=var, width=1)
            entry.grid(row=0, column=0, sticky="ew", ipady=theme.px(5), padx=(0, theme.px(6)))
            entry.bind("<Return>", lambda _: on_enter())
            theme.button(row, button_text, command, icon=icon).grid(row=0, column=1, sticky="ns")
            return row, entry

        self._mem_insert_var = tk.StringVar()
        _, self._mem_insert_entry = field_row("Lembrar um fato", self._mem_insert_var, self._mem_do_insert,
                                              "Adicionar", self._mem_do_insert, "add")
        self._mem_search_var = tk.StringVar()
        search_row, self._mem_search_entry = field_row("Buscar", self._mem_search_var, self._mem_do_search,
                                                       "Buscar", self._mem_do_search, "search")
        theme.button(search_row, "Todos", self._mem_show_all).grid(row=0, column=2, sticky="ns", padx=(theme.px(4), 0))

        theme.section(parent, "Fatos guardados").pack(fill=tk.X, padx=pad, pady=(theme.px(12), theme.px(4)))
        # Clear-all button packed before the list so it stays visible at the bottom.
        theme.button(parent, "Apagar tudo", self._mem_clear_all, kind="danger",
                     icon="delete").pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=pad)

        list_outer = tk.Frame(parent, bg=theme.GLASS)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=(pad, theme.px(4)))
        scrollbar = ttk.Scrollbar(list_outer, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._mem_canvas = tk.Canvas(list_outer, bg=theme.INPUT, highlightthickness=0, width=1,
                                     yscrollcommand=scrollbar.set)
        self._mem_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._mem_canvas.yview)

        self._mem_wrap = theme.px(200)
        self._mem_inner = tk.Frame(self._mem_canvas, bg=theme.INPUT)
        self._mem_canvas_window = self._mem_canvas.create_window((0, 0), window=self._mem_inner, anchor="nw")
        self._mem_inner.bind("<Configure>", self._mem_on_inner_resize)
        self._mem_canvas.bind("<Configure>", self._mem_on_canvas_resize)
        self._mem_canvas.bind("<MouseWheel>",
            lambda e: self._mem_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        # first refresh triggered by _on_stores_ready

    def _mem_on_inner_resize(self, _=None):
        self._mem_canvas.configure(scrollregion=self._mem_canvas.bbox("all"))

    def _mem_on_canvas_resize(self, event):
        self._mem_canvas.itemconfig(self._mem_canvas_window, width=event.width)
        self._mem_wrap = max(theme.px(120), event.width - theme.px(48))
        for row in self._mem_inner.winfo_children():
            for label in row.winfo_children():
                if getattr(label, "_wraps", False):
                    label.config(wraplength=self._mem_wrap)

    # ── Qdrant helpers ────────────────────────────────────────────────────────

    def _mem_fetch_all(self):
        store = self._ltm_store
        if store is None or not store.available:
            return False, 0, []
        items = store.list_all(500)
        return True, store.count(), items

    def _mem_fetch_search(self, query: str):
        if self._ltm_store is None:
            return []
        return self._ltm_store.search_text_gui(query)

    # ── List rendering ────────────────────────────────────────────────────────

    def _mem_render_items(self, available: bool, count: int, items: list,
                          mode: str = "all"):
        # Atualiza status + count
        if available:
            self._mem_dot.config(fg=theme.OK)
            self._mem_status_var.set("Conectada")
            self._mem_count_var.set(f"{count} fatos")
        else:
            self._mem_dot.config(fg=theme.DANGER)
            self._mem_status_var.set("Indisponível")
            self._mem_count_var.set("")

        # Limpa lista
        for w in self._mem_inner.winfo_children():
            w.destroy()

        if not available:
            tk.Label(self._mem_inner, text="Memória indisponível",
                     bg=theme.INPUT, fg=theme.MUTED,
                     font=theme.FONT_SMALL,
                     padx=8, pady=6).pack(anchor="w")
            return

        if not items:
            msg = ("nenhum resultado" if mode == "search"
                   else "nenhum fato guardado ainda")
            tk.Label(self._mem_inner, text=msg,
                     bg=theme.INPUT, fg=theme.MUTED,
                     font=theme.FONT_SMALL,
                     padx=8, pady=6).pack(anchor="w")
            return

        for item in items:
            self._mem_render_row(item, mode)

        self._mem_canvas.yview_moveto(0)

    def _mem_render_row(self, item: dict, mode: str):
        ts_raw = item.get("ts", "")
        try:
            dt = datetime.datetime.fromisoformat(ts_raw)
            ts_fmt = dt.strftime("%d/%m %H:%M")
        except Exception:
            ts_fmt = ts_raw[:16]

        score_txt = (f"  {item['score']:.0%}" if mode == "search" and "score" in item
                     else "")

        row = tk.Frame(self._mem_inner, bg=theme.INPUT, pady=3)
        row.pack(fill=tk.X, padx=4)
        row.grid_columnconfigure(0, weight=1)

        text_lbl = tk.Label(
            row, text=item["text"],
            bg=theme.INPUT, fg=theme.TEXT,
            font=theme.FONT, wraplength=self._mem_wrap,
            justify="left", anchor="nw",
        )
        text_lbl._wraps = True
        text_lbl.grid(row=0, column=0, sticky="ew", padx=(4, 2))

        point_id = item["id"]
        del_btn = tk.Button(
            row, text=theme.ICON["close"],
            command=lambda pid=point_id: self._mem_delete_one(pid),
            bg=theme.INPUT, fg=theme.DANGER,
            activebackground=theme.DANGER_BG, activeforeground=theme.DANGER,
            font=theme.FONT_SMALL,
            relief=tk.FLAT, padx=3, pady=0,
            cursor="hand2", bd=0,
        )
        del_btn.grid(row=0, column=1, sticky="ne", padx=(0, 2))

        tk.Label(
            row, text=f"{ts_fmt}{score_txt}",
            bg=theme.INPUT, fg=theme.MUTED,
            font=theme.FONT_SMALL, anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=(4, 2), pady=(0, 2))

        tk.Frame(self._mem_inner, bg=theme.BORDER, height=1).pack(fill=tk.X, padx=4)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _mem_show_all(self):
        def _run():
            ok, count, items = self._mem_fetch_all()
            self.root.after(0, lambda: self._mem_render_items(ok, count, items, "all"))
        threading.Thread(target=_run, daemon=True).start()
        if self._mem_map_open:
            self._mem_graph_refresh()
        # Auto-refresh every 15 s; debounced, or every insert/delete would add another timer.
        self._debounce("memory_refresh", 15000, self._mem_show_all)

    def _mem_do_search(self):
        query = self._mem_search_var.get().strip()
        if not query:
            return

        def _run():
            results = self._mem_fetch_search(query)
            _, count, _ = self._mem_fetch_all()
            self.root.after(0, lambda: self._mem_render_items(True, count, results, "search"))
        threading.Thread(target=_run, daemon=True).start()

    def _mem_do_insert(self):
        if self._ltm_store is None:
            return
        text = self._mem_insert_var.get().strip()
        if not text:
            return

        self._mem_insert_var.set("")
        self._mem_status_var.set("Guardando…")

        def _run():
            self._ltm_store.upsert(text)
            self.root.after(0, self._mem_show_all)
        threading.Thread(target=_run, daemon=True).start()

    def _mem_delete_one(self, point_id):
        if self._ltm_store is None:
            return
        def _run():
            self._ltm_store.delete_one(point_id)
            self.root.after(0, self._mem_show_all)
        threading.Thread(target=_run, daemon=True).start()

    def _mem_clear_all(self):
        if self._ltm_store is None:
            return
        def _run():
            self._ltm_store.clear()
            self.root.after(0, self._mem_show_all)
        threading.Thread(target=_run, daemon=True).start()

    # ── Memory map (main screen, under the appearance) ───────────────────────

    def _build_memory_map(self, parent):
        """The graph sits under the appearance, in view during the conversation (it explains the
        reply that was just given); minimized it keeps one line saying what the last reply used."""
        self._mem_map_open = bool(SETTINGS.get("memory.map_open"))
        self._mem_used = dict(_EMPTY_USE)
        self._mem_used_any = False            # no reply yet in this session
        self._mem_open_docs: set[str] = set()
        self._mem_graph_sig = None

        header = tk.Frame(parent, bg=theme.GLASS)
        header.pack(fill=tk.X)
        header.grid_columnconfigure(1, weight=1)
        tk.Label(header, text="Mapa da memória", bg=theme.GLASS, fg=theme.TEXT2,
                 font=theme.FONT_BOLD).grid(row=0, column=0, sticky="w")
        self._mem_map_status = tk.StringVar(value="")
        tk.Label(header, textvariable=self._mem_map_status, bg=theme.GLASS, fg=theme.MUTED, font=theme.FONT_SMALL,
                 anchor="w").grid(row=0, column=1, sticky="ew", padx=theme.px(10))
        self._mem_graph_search = tk.StringVar()
        self._mem_map_entry = theme.entry(header, textvariable=self._mem_graph_search, width=16)
        self._mem_map_entry.grid(row=0, column=2, ipady=theme.px(2), padx=(0, theme.px(6)))
        self._mem_map_entry.bind("<KeyRelease>", lambda _e: self._mem_graph_apply_search())
        self._mem_map_toggle = theme.button(header, "", lambda: self._mem_map_set_open(not self._mem_map_open),
                                            font=theme.FONT_SMALL)
        self._mem_map_toggle.grid(row=0, column=3)

        self._mem_map_body = tk.Frame(parent, bg=theme.GLASS, height=theme.px(220))
        self._mem_map_body.pack_propagate(False)
        parent = self._mem_map_body

        # Details of the clicked point float over the map (packed above it, they squeezed the
        # drawing into a strip); ✕ only closes them.
        self._mem_detail = tk.Frame(parent, bg=theme.GLASS_HI, highlightthickness=1,
                                    highlightbackground=theme.BORDER)
        self._mem_detail.grid_columnconfigure(0, weight=1)
        self._mem_detail_text = tk.Label(self._mem_detail, bg=theme.GLASS_HI, fg=theme.TEXT, font=theme.FONT,
                                         justify="left", anchor="w", wraplength=theme.px(260))
        self._mem_detail_text.grid(row=0, column=0, sticky="ew", padx=(theme.px(10), 0), pady=(theme.px(8), theme.px(2)))
        tk.Button(self._mem_detail, text=theme.ICON["close"], command=self._mem_detail_close, bg=theme.GLASS_HI,
                  fg=theme.TEXT2, activebackground=theme.HOVER, activeforeground=theme.TEXT, font=theme.FONT,
                  relief=tk.FLAT, bd=0, padx=theme.px(8), cursor="hand2").grid(row=0, column=1, sticky="ne",
                                                                             padx=theme.px(4), pady=theme.px(4))
        self._mem_detail_meta = tk.Label(self._mem_detail, bg=theme.GLASS_HI, fg=theme.MUTED, font=theme.FONT_SMALL,
                                         justify="left", anchor="w")
        self._mem_detail_meta.grid(row=1, column=0, columnspan=2, sticky="ew", padx=theme.px(10), pady=(0, theme.px(8)))
        self._mem_detail_button = theme.button(self._mem_detail, "", None)
        self._mem_detail_button.grid(row=2, column=0, columnspan=2, sticky="e", padx=theme.px(10), pady=(0, theme.px(8)))
        self._mem_detail.bind("<Configure>", lambda e: self._mem_detail_text.config(
            wraplength=max(theme.px(120), e.width - theme.px(60))))

        self._mem_graph = MemoryGraphView(parent, on_select=self._mem_graph_select)
        self._mem_graph.pack(fill=tk.BOTH, expand=True, pady=(theme.px(4), 0))
        self._mem_map_set_open(self._mem_map_open, save=False)

    def _mem_map_set_open(self, open_: bool, save: bool = True):
        self._mem_map_open = open_
        self._mem_map_toggle.config(text="Minimizar" if open_ else "Mostrar mapa")
        if open_:
            self._mem_map_body.pack(fill=tk.X, pady=(theme.px(4), 0))
            self._mem_map_entry.grid()
        else:
            self._mem_map_body.pack_forget()
            self._mem_map_entry.grid_remove()
        if save:
            SETTINGS.set("memory.map_open", open_)
        if open_ and getattr(self, "_ltm_store", None) is not None:
            self._mem_graph_refresh(force=True)
            self._mem_graph.start()             # resumes a layout that was paused while hidden

    def _mem_fit_map(self, center_height: int):
        """About a third of the center column, so the appearance keeps most of it."""
        self._mem_map_body.config(height=max(theme.px(150), min(theme.px(340), int(center_height * 0.32))))

    def _mem_graph_refresh(self, force: bool = False):
        """Rebuilds the graph in the background, only when something changed (the list refreshes
        every 15 s). Positions are kept, so a new memory does not make the drawing start over."""
        ltm, kb = self._ltm_store, getattr(self, "_kb_store", None)
        used, open_docs = self._mem_used, set(self._mem_open_docs)
        previous = self._mem_graph.layout.positions() if self._mem_graph.layout is not None else None

        def _run():
            if ltm is None or not ltm.available:
                self.root.after(0, lambda: self._mem_graph.message("Memória indisponível."))
                return
            memories = ltm.list_for_graph()
            docs = kb.list_documents() if kb is not None and kb.available else []
            wanted = {tuple(p) for p in used["pieces"]}
            by_source = {d["source"]: d["doc_id"] for d in docs}
            pieces = []
            for doc_id in open_docs | {by_source[f] for f, _w in wanted if f in by_source}:
                pieces += [p for p in kb.pieces_of(doc_id)
                           if doc_id in open_docs or (p["source"], p.get("where", "")) in wanted]
            sig = (tuple(sorted((str(m["id"]), m["topic"] or "") for m in memories)),
                   tuple(d["doc_id"] for d in docs), frozenset(open_docs), frozenset(wanted))
            if not force and sig == self._mem_graph_sig and self._mem_graph.graph is not None:
                self.root.after(0, self._mem_graph_restyle)
                return
            g = memory_graph.build(memories, docs, pieces)
            layout = memory_graph.Layout(g, previous=previous)
            if previous is None:
                layout.settle(100)               # first drawing already close to its place (~1 s)
            self.root.after(0, lambda: self._mem_graph_show(sig, g, layout, bool(memories or docs)))
        threading.Thread(target=_run, daemon=True).start()

    def _mem_graph_show(self, sig, g, layout, anything: bool):
        self._mem_graph_sig = sig
        if not anything:
            self._mem_graph.message("Nenhuma memória ainda. Elas aparecem aqui conforme você conversa.")
            return
        self._mem_graph.show(g, layout)
        self._mem_graph_restyle()

    def _mem_graph_restyle(self):
        g = self._mem_graph.graph
        if g is None:
            return
        self._mem_graph.set_used(memory_graph.used_nodes(g, self._mem_used))
        self._mem_graph_apply_search()

    def _mem_map_update_status(self):
        n_mem = len(self._mem_used["profile"]) + len(self._mem_used["memories"])
        n_pieces = len(self._mem_used["pieces"])
        if not self._mem_used_any:
            text = ""
        elif n_mem or n_pieces:
            text = f"Usou {n_mem} memória{'s' if n_mem != 1 else ''} · {n_pieces} trecho{'s' if n_pieces != 1 else ''}"
        else:
            text = "Não usou memória"
        self._mem_map_status.set(text)

    def _mem_graph_apply_search(self):
        g = self._mem_graph.graph
        if g is None:
            return
        term = self._mem_graph_search.get().strip()
        self._mem_graph.set_found(memory_graph.matches(g, term) if term else None)

    def _mem_on_context_used(self, used: dict):
        """context_used from the agent loop: what went to the model in the last reply."""
        self._mem_used = {**_EMPTY_USE, **(used or {})}
        self._mem_used_any = True
        self._mem_map_update_status()          # also while minimized
        if self._mem_map_open:
            self._mem_graph_refresh()

    def _mem_detail_close(self):
        self._mem_detail.place_forget()

    def _mem_graph_select(self, node):
        if node is None:
            self._mem_detail_close()
            return
        button, text = self._mem_detail_button, node.text
        if node.kind == "memory":
            kind = "Perfil" if node.topic == "perfil" else "Fato"
            meta = f"{kind} · {node.topic} · {self._mem_format_ts(node.ts)}"
            button.config(text=f"{theme.ICON['delete']}  Apagar", command=lambda: self._mem_graph_delete(node))
            theme.set_kind(button, "danger")
        elif node.kind == "document":
            meta = "Documento da Base"
            opened = node.ref in self._mem_open_docs
            button.config(text="Esconder partes" if opened else "Mostrar partes",
                          command=lambda: self._mem_graph_toggle_doc(node.ref))
            theme.set_kind(button, "normal")
        else:
            if node.kind == "piece":
                meta = f"Trecho de documento · {node.where}" if node.where else "Trecho de documento"
            else:
                members = sum(1 for n in self._mem_graph.graph.nodes if n.kind == "memory" and n.topic == node.topic)
                text, meta = node.label, f"Assunto · {members} memória(s)"
        if node.kind in ("memory", "document"):
            button.grid()
        else:
            button.grid_remove()                     # topics and pieces: nothing to do but read
        self._mem_detail_text.config(text=text)
        self._mem_detail_meta.config(text=meta)
        self._mem_detail.place(relx=1.0, rely=0.0, x=0, y=theme.px(30), anchor="ne", relwidth=0.6)
        self._mem_detail.lift()

    def _mem_graph_toggle_doc(self, doc_id):
        self._mem_open_docs ^= {doc_id}
        self._mem_detail_close()
        self._mem_graph_refresh()

    def _mem_graph_delete(self, node):
        if not messagebox.askyesno("Apagar memória", f"Apagar esta memória?\n\n{node.text}", parent=self.root):
            return
        self._mem_detail_close()
        self._mem_delete_one(node.ref)

    @staticmethod
    def _mem_format_ts(ts_raw: str) -> str:
        try:
            return datetime.datetime.fromisoformat(ts_raw).strftime("%d/%m %H:%M")
        except Exception:
            return ts_raw[:16]
