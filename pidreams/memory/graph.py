"""Memory graph: nodes and links from the memories and the documents, and a force layout.

No Tk here, so it is tested without a window; pidreams/ui/memory_graph.py draws it.
Memories gather around their topic (see topics.py for why not by vector alone) and each one
links to the most similar memory of the same topic, using the vectors already stored.
Documents are bigger nodes; their pieces only appear when the document is open or when a
piece was used in the last turn (a 100-page PDF has ~400 pieces).
"""

import unicodedata
from dataclasses import dataclass, field

import numpy as np

from pidreams.memory import topics


@dataclass
class Node:
    key: str            # "t:família", "m:<id>", "d:<doc_id>", "p:<file>|<where>"
    kind: str           # topic | memory | document | piece
    label: str
    text: str = ""
    topic: str = ""
    ts: str = ""
    ref: object = None  # memory point id or doc_id
    where: str = ""     # piece position (p. 3, slide 2...)


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple[int, int, str]] = field(default_factory=list)   # (a, b, "belongs" | "similar")

    def index(self) -> dict[str, int]:
        return {n.key: i for i, n in enumerate(self.nodes)}


def piece_key(source: str, where: str) -> str:
    return f"p:{source}|{where}"


def build(memories: list[dict], documents: list[dict] = (), pieces: list[dict] = ()) -> Graph:
    """memories: LTMStore.list_for_graph(); documents: KBStore.list_documents();
    pieces: the pieces to show (of open documents, and the ones used in the last turn)."""
    g = Graph()
    groups: dict[str, list[dict]] = {}
    for m in memories:
        topic = topics.PROFILE if m.get("kind") == "perfil" else (m.get("topic") or topics.UNTAGGED)
        groups.setdefault(topic, []).append(m)
    for topic, members in groups.items():
        anchor = len(g.nodes)
        g.nodes.append(Node(f"t:{topic}", "topic", topic.capitalize(), topic=topic))
        first = len(g.nodes)
        for m in members:
            g.nodes.append(Node(f"m:{m['id']}", "memory", m["text"], text=m["text"], topic=topic,
                                ts=m.get("ts", ""), ref=m["id"]))
            g.edges.append((anchor, len(g.nodes) - 1, "belongs"))
        g.edges += _similar(members, first)
    docs = {}
    for d in documents:
        docs[d["doc_id"]] = len(g.nodes)
        g.nodes.append(Node(f"d:{d['doc_id']}", "document", d["source"], ref=d["doc_id"],
                            text=f"{d['source']} — {d.get('count', 0)} partes", ts=d.get("ts", "")))
    for p in pieces:
        if p.get("doc_id") not in docs:
            continue
        g.nodes.append(Node(piece_key(p["source"], p.get("where", "")), "piece", p.get("where") or p["source"],
                            text=p.get("text", ""), ref=p["doc_id"], where=p.get("where", "")))
        g.edges.append((docs[p["doc_id"]], len(g.nodes) - 1, "belongs"))
    return g


def _similar(members: list[dict], first: int) -> list[tuple[int, int, str]]:
    """Each memory → its most similar memory in the same topic; a pair only once."""
    vectors = [m.get("vector") for m in members]
    if len(members) < 2 or any(v is None for v in vectors):
        return []
    v = np.asarray(vectors, dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    sim = v @ v.T
    np.fill_diagonal(sim, -2)
    pairs = {tuple(sorted((i, int(j)))) for i, j in enumerate(sim.argmax(axis=1))}
    return [(first + a, first + b, "similar") for a, b in sorted(pairs)]


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def matches(graph: Graph, term: str) -> set[int]:
    """Nodes whose text or label contains the term, ignoring accents and case."""
    term = _plain(term.strip())
    if not term:
        return set()
    return {i for i, n in enumerate(graph.nodes) if term in _plain(n.text or n.label)}


def used_nodes(graph: Graph, used: dict) -> set[int]:
    """used: the context_used event — {profile, memories, pieces: [[file, where]]}."""
    texts = set(used.get("profile", [])) | set(used.get("memories", []))
    keys = {piece_key(f, w) for f, w in used.get("pieces", [])}
    return {i for i, n in enumerate(graph.nodes)
            if (n.kind == "memory" and n.text in texts) or (n.kind == "piece" and n.key in keys)}


# Ideal link length and node spacing, in world units (the widget scales to the window).
_LINK = {"belongs": 85.0, "similar": 60.0}
_SPACING = 70.0


class Layout:
    """Force layout: every pair pushes apart, links pull together, a weak pull to the centre.
    The step size cools down each step; when it is small the drawing is settled and nothing is
    computed any more. Measured: 11 ms per step with 500 nodes (numpy, 2026-10-31).

    previous: {node key: (x, y)} of an earlier layout, so a new or deleted memory does not
    make the whole drawing start over."""

    def __init__(self, graph: Graph, previous: dict | None = None, seed: int = 314):
        self.graph = graph
        rng = np.random.default_rng(seed)
        n = len(graph.nodes)
        self.pos = np.zeros((n, 2))
        anchors = [i for i, nd in enumerate(graph.nodes) if nd.kind in ("topic", "document")]
        ring = max(150.0, 30.0 * len(anchors))
        for k, i in enumerate(anchors):
            a = 2 * np.pi * k / max(1, len(anchors))
            self.pos[i] = (ring * np.cos(a), ring * np.sin(a))
        parent = {b: a for a, b, kind in graph.edges if kind == "belongs"}
        for i, nd in enumerate(graph.nodes):
            if i not in anchors:
                self.pos[i] = self.pos[parent.get(i, 0)] + rng.normal(scale=25.0, size=2)
        kept = 0
        for i, nd in enumerate(graph.nodes):
            if previous and nd.key in previous:
                self.pos[i] = previous[nd.key]
                kept += 1
        self.edges = np.array([(a, b) for a, b, _ in graph.edges], dtype=int).reshape(-1, 2)
        self.lengths = np.array([_LINK[k] for _, _, k in graph.edges]).reshape(-1, 1)
        # A drawing that mostly existed already only needs to settle the new nodes.
        self.heat = 6.0 if previous and kept > n / 2 else 30.0

    @property
    def settled(self) -> bool:
        return self.heat < 0.4 or len(self.pos) < 2

    def step(self) -> None:
        p = self.pos
        if len(p) < 2:
            return
        d = p[:, None, :] - p[None, :, :]
        dist2 = (d ** 2).sum(-1) + 1.0
        push = (d / dist2[..., None]).sum(1) * _SPACING ** 2
        pull = np.zeros_like(p)
        if len(self.edges):
            a, b = self.edges[:, 0], self.edges[:, 1]
            delta = p[a] - p[b]
            dist = np.linalg.norm(delta, axis=1, keepdims=True) + 1e-6
            force = delta * ((dist - self.lengths) / dist) * 0.5
            np.add.at(pull, a, -force)
            np.add.at(pull, b, force)
        move = push + pull - p * 0.02
        size = np.linalg.norm(move, axis=1, keepdims=True) + 1e-9
        self.pos = p + move / size * np.minimum(size, self.heat)
        self.heat *= 0.96

    def settle(self, steps: int) -> None:
        for _ in range(steps):
            if self.settled:
                return
            self.step()

    def positions(self) -> dict:
        return {nd.key: tuple(self.pos[i]) for i, nd in enumerate(self.graph.nodes)}
