"""Memory graph view: draws a pidreams.memory.graph.Graph on a Canvas, in the app's glass-neon style.

Canvas items are created once per graph and only moved (coords) while the layout settles;
once it is settled no frame is drawn, and nothing runs while the view is hidden. Measured:
1179 links + 500 points moved in 5.5 ms per frame, a layout step 11 ms (2026-10-31).
"""

import tkinter as tk

import numpy as np

from pidreams.memory.graph import Graph, Layout
from pidreams.ui import theme

_FRAME_MS = 33                       # ≤ 30 frames/s, only while settling
_RADIUS = {"topic": 9, "memory": 5, "document": 11, "piece": 4}
_COLOR = {"perfil": theme.VIOLET, "fato": theme.CYAN, "document": theme.PEACH, "piece": theme.PEACH}
_USED = theme.WARN                   # ring around what the assistant used in the last turn
_LEGEND = [("perfil", theme.VIOLET), ("fato", theme.CYAN), ("documento", theme.PEACH), ("usado agora", _USED)]


def _trails(graph: Graph) -> list[tuple[str, list[int]]]:
    """The links as a few continuous lines instead of one line each: painting 518 loose lines
    cost ~17 ms per frame (the same was measured in the digital brain appearance). Every node of
    a group links to its anchor (topic or document), so the whole group can be traced in one
    line that goes out to each node and back through the anchor. For similar links the trips
    back are drawn under the "belongs" trail, which hides them."""
    parent = {b: a for a, b, kind in graph.edges if kind == "belongs"}
    belongs: dict[int, list[int]] = {}
    similar: dict[int, list[int]] = {}
    for a, b, kind in graph.edges:
        if kind == "belongs":
            belongs.setdefault(a, [a]).extend((b, a))
        elif parent.get(a) is not None and parent.get(a) == parent.get(b):
            anchor = parent[a]
            similar.setdefault(anchor, [anchor]).extend((a, b, a, anchor))
    return [("similar", p) for p in similar.values()] + [("belongs", p) for p in belongs.values()]


class MemoryGraphView(tk.Frame):
    def __init__(self, parent, on_select=None):
        super().__init__(parent, bg=theme.INPUT)
        self.canvas = tk.Canvas(self, bg=theme.INPUT, highlightthickness=0, width=1, height=1)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.on_select = on_select           # callback(node) or None for a click on the background
        self.graph: Graph | None = None
        self.layout: Layout | None = None
        self.used: set[int] = set()
        self.found: set[int] | None = None   # search result; None = no search
        self.scale, self.offset = 1.0, [0.0, 0.0]
        self._items: dict[int, int] = {}     # canvas id → node index
        self._edge_items: list[int] = []
        self._node_items: list[int] = []
        self._ring_items: list[int] = []
        self._label_items: dict[int, int] = {}
        self._job = None
        self._drag = None
        self._fitted = False
        self._user_moved = False             # zoomed or dragged: stop re-framing on our own
        self.canvas.bind("<MouseWheel>", self._zoom)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Configure>", lambda _e: self._fit() if not self._fitted else self.redraw())

    # ── content ──

    def message(self, text: str) -> None:
        """Empty or unavailable memory: a sentence instead of an empty drawing."""
        self.stop()
        self.graph = self.layout = None
        self.canvas.delete("all")
        self.canvas.create_text(theme.px(16), theme.px(16), text=text, anchor="nw", fill=theme.MUTED,
                                font=theme.FONT, width=max(theme.px(160), self.canvas.winfo_width() - theme.px(32)))

    def show(self, graph: Graph, layout: Layout) -> None:
        self.stop()
        keep_view = self.graph is not None
        self.graph, self.layout = graph, layout
        self.canvas.delete("all")
        self._items.clear()
        self._label_items.clear()
        # Similar links first, so the "belongs" trails drawn on top hide the trips back to the anchor.
        self._paths = _trails(graph)
        self._edge_items = [self.canvas.create_line(0, 0, 0, 0, 0, 0, width=1,
                                                    fill=theme.BORDER if kind == "belongs" else theme.blend(theme.CYAN, 0.35, theme.INPUT))
                            for kind, _path in self._paths]
        self._ring_items, self._node_items = [], []
        for i, node in enumerate(graph.nodes):
            self._ring_items.append(self.canvas.create_oval(0, 0, 0, 0, outline="", width=2))
            item = self.canvas.create_oval(0, 0, 0, 0, outline="", fill=self._color(node))
            self._node_items.append(item)
            self._items[item] = i
            if node.kind in ("topic", "document"):
                name = node.label if len(node.label) <= 24 else node.label[:22] + "…"
                self._label_items[i] = self.canvas.create_text(0, 0, text=name, fill=theme.TEXT2,
                                                               font=theme.FONT_SMALL, anchor="s")
        self._draw_legend()
        self._fitted = keep_view and self._fitted
        if not self._fitted:
            self._fit()
        self._restyle()
        self.redraw()
        self.start()

    def set_used(self, used: set[int]) -> None:
        self.used = used
        self._restyle()

    def set_found(self, found: set[int] | None) -> None:
        self.found = found
        self._restyle()

    # ── animation ──

    def start(self) -> None:
        if self._job is None and self.layout is not None and not self.layout.settled:
            self._job = self.after(_FRAME_MS, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _tick(self) -> None:
        self._job = None
        if self.layout is None or not self.winfo_ismapped():
            return                                   # hidden: no work; start() again when shown
        self.layout.step()
        if self.layout.settled and not self._user_moved:
            self._fit()                              # final shape framed, names inside the strip
        self.redraw()
        self.start()

    # ── drawing ──

    def _color(self, node) -> str:
        if node.kind == "topic":
            return theme.MUTED
        if node.kind == "memory":
            return _COLOR["perfil" if node.topic == "perfil" else "fato"]
        return _COLOR[node.kind]

    def _screen(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def _fit(self) -> None:
        """Whole drawing in the window, centred."""
        if self.layout is None or not len(self.layout.pos):
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 10 or h < 10:
            return
        # Margins leave room for the names beside the edge points and for the legend on top
        # (names were cut off); width and height scale apart, the map is a wide strip.
        p = self.layout.pos
        side, top = theme.px(70), theme.px(34)
        scale_x = max(w - 2 * side, 10) / max(float(np.ptp(p[:, 0])), 1.0)
        scale_y = max(h - top - theme.px(16), 10) / max(float(np.ptp(p[:, 1])), 1.0)
        self.scale = min(scale_x, scale_y)
        cx, cy = (p[:, 0].min() + p[:, 0].max()) / 2, (p[:, 1].min() + p[:, 1].max()) / 2
        self.offset = [w / 2 - cx * self.scale, (h + top - theme.px(16)) / 2 - cy * self.scale]
        self._fitted = True
        self.redraw()

    def redraw(self) -> None:
        if self.graph is None or self.layout is None:
            return
        pts = [self._screen(x, y) for x, y in self.layout.pos]
        for item, (_kind, path) in zip(self._edge_items, self._paths):
            self.canvas.coords(item, *[c for i in path for c in pts[i]])
        zoom = max(0.6, min(1.8, self.scale))
        for i, node in enumerate(self.graph.nodes):
            x, y = pts[i]
            r = theme.px(_RADIUS[node.kind]) * zoom
            self.canvas.coords(self._node_items[i], x - r, y - r, x + r, y + r)
            self.canvas.coords(self._ring_items[i], x - r - 4, y - r - 4, x + r + 4, y + r + 4)
            if i in self._label_items:
                self.canvas.coords(self._label_items[i], x, y - r - 3)

    def _restyle(self) -> None:
        """Colours for the search (dim what does not match) and the ring for what was used."""
        if self.graph is None:
            return
        for i, node in enumerate(self.graph.nodes):
            dim = self.found is not None and i not in self.found
            base = self._color(node)
            self.canvas.itemconfig(self._node_items[i], fill=theme.blend(base, 0.25, theme.INPUT) if dim else base)
            self.canvas.itemconfig(self._ring_items[i], outline=_USED if i in self.used else "")
            if i in self._label_items:
                self.canvas.itemconfig(self._label_items[i], fill=theme.MUTED if dim else theme.TEXT2)

    def _draw_legend(self) -> None:
        x, y = theme.px(10), theme.px(10)
        for text, color in _LEGEND:
            r = theme.px(4)
            self.canvas.create_oval(x, y, x + 2 * r, y + 2 * r, fill=color if text != "usado agora" else "",
                                    outline=color if text == "usado agora" else "", width=2)
            label = self.canvas.create_text(x + 2 * r + theme.px(4), y + r, text=text, anchor="w",
                                            fill=theme.TEXT2, font=theme.FONT_SMALL)
            x = self.canvas.bbox(label)[2] + theme.px(12)

    # ── mouse ──

    def _zoom(self, event) -> None:
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self.offset = [event.x - (event.x - self.offset[0]) * factor, event.y - (event.y - self.offset[1]) * factor]
        self.scale *= factor
        self._user_moved = True
        self.redraw()

    def _press(self, event) -> None:
        self._drag = (event.x, event.y, False)

    def _move(self, event) -> None:
        if self._drag is None:
            return
        x0, y0, _moved = self._drag
        self.offset[0] += event.x - x0
        self.offset[1] += event.y - y0
        self._drag = (event.x, event.y, True)
        self._user_moved = True
        self.redraw()

    def _release(self, event) -> None:
        moved = self._drag is not None and self._drag[2]
        self._drag = None
        if moved or self.graph is None or self.on_select is None:
            return
        hit = self.canvas.find_overlapping(event.x - 3, event.y - 3, event.x + 3, event.y + 3)
        nodes = [self._items[h] for h in hit if h in self._items]
        self.on_select(self.graph.nodes[nodes[-1]] if nodes else None)
