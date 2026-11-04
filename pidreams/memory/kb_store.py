"""Knowledge base: pasted texts and documents (PDF, Word, slides, spreadsheets, text), searched by
meaning AND by exact word, each piece remembering where it came from.

Every piece has two vectors: the dense one (meaning) and a sparse one of its words (terms.py) whose
IDF Qdrant computes. Search fuses both with DBSF: RRF only looks at positions and lost "contrato
2024-0815" to "2024-0816" (they tie on meaning); DBSF keeps the margin of the word match and got all
four test questions first (measured 2026-11-01).
"""

import hashlib
import logging
import random
import threading
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, Fusion, FusionQuery, HnswConfigDiff, MatchValue, Modifier,
    OptimizersConfigDiff, PointStruct, Prefetch, SparseVectorParams, VectorParams,
)

from pidreams.core.config import CONFIG
from pidreams.memory import documents, terms
from pidreams.memory.chunker import split_text
from pidreams.memory.embedder import FastEmbedManager

log = logging.getLogger(__name__)

# Pieces per embedding batch. Small batches pad less: 185-189 ms per piece at 4-8 versus 203 at 32
# (measured 2026-10-31, CPU); cancel and progress also react sooner.
_BATCH = 8
_PREFETCH = 20


def doc_id_for(key: str) -> str:
    """Same file (absolute path) or same pasted title → same id, so saving again replaces it."""
    return hashlib.sha1(key.casefold().encode("utf-8")).hexdigest()[:16]


def label(item: dict) -> str:
    """Origin shown to the model and in the panel: "contrato.pdf · p. 12"."""
    return f"{item['source']} · {item['where']}" if item.get("where") else item["source"]


class KBStore:
    COLLECTION = "pi_dreams_docs"
    _OLD_COLLECTION = "pi_dreams_kb"        # before v0.4.0: dense vector only, no word search

    def __init__(self, client=None, embedder=None):
        """Accepts an existing QdrantClient and FastEmbedManager to avoid two clients
        competing for the same embedded Qdrant path."""
        self.available = False
        try:
            self._client = client if client is not None else QdrantClient(path=CONFIG.qdrant_path)
            self._embedder = embedder if embedder is not None else FastEmbedManager(CONFIG.ltm_embedding_model)
            self._ensure_collection()
            self._migrate_old_collection()
            self.available = True
            log.info(f"[KB] Qdrant connected — collection '{self.COLLECTION}'")
        except Exception as e:
            log.warning(f"[KB] Qdrant unavailable: {e}")

    # ── collection ───────────────────────────────────────────────────────────

    def _ensure_collection(self):
        existing = {c.name for c in self._client.get_collections().collections}
        if self.COLLECTION not in existing:
            self._client.create_collection(
                collection_name=self.COLLECTION,
                vectors_config={"dense": VectorParams(size=self._embedder.vector_size, distance=Distance.COSINE)},
                sparse_vectors_config={"terms": SparseVectorParams(modifier=Modifier.IDF)},
                optimizers_config=OptimizersConfigDiff(indexing_threshold=100),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
            )

    def _migrate_old_collection(self):
        """Pasted texts from before v0.4.0 move to the new collection (Qdrant cannot add a sparse
        vector to an existing one). The old collection goes only after the counts match."""
        if self._OLD_COLLECTION not in {c.name for c in self._client.get_collections().collections}:
            return
        points, _ = self._client.scroll(self._OLD_COLLECTION, limit=100_000, with_payload=True)
        by_source: dict[str, list[str]] = {}
        for p in points:
            if p.payload and p.payload.get("text"):
                by_source.setdefault(p.payload.get("source") or "(sem título)", []).append(p.payload["text"])
        moved = sum(self._store_pieces(doc_id_for("texto:" + s), s, "texto", [("", t) for t in texts])
                    for s, texts in by_source.items())
        # A long old text may become more than one piece: at least one piece per old text is complete.
        if moved >= sum(len(t) for t in by_source.values()):
            self._client.delete_collection(self._OLD_COLLECTION)
            log.info("[KB] %d pieces moved to %s", moved, self.COLLECTION)
        else:
            log.warning("[KB] migration incomplete (%d moved); old collection kept", moved)

    # ── saving ───────────────────────────────────────────────────────────────

    def _split(self, sections: list[tuple[str, str]], number: bool) -> list[tuple[str, str]]:
        """Sections (page, slide, sheet…) → pieces the size the base already uses. With number=True,
        pieces from a section without a position become "trecho N" (pasted texts keep none)."""
        pieces, counter = [], 0
        for where, text in sections:
            for part in split_text(text, mode="sentence", sentences_size=CONFIG.kb_chunk_size,
                                   sentences_overlap=CONFIG.kb_chunk_overlap):
                if not isinstance(part, str) or not part.strip():
                    continue
                if not where and number:
                    counter += 1
                pieces.append((where or (f"trecho {counter}" if number else ""), part))
        return pieces

    def _store_pieces(self, doc_id: str, source: str, kind: str, sections: list[tuple[str, str]],
                      progress=None, cancel: threading.Event | None = None, path: str = "") -> int:
        pieces = self._split(sections, number=kind != "texto")
        self.delete_document(doc_id)                       # saving again replaces
        ts = datetime.now(timezone.utc).isoformat()
        stored = 0
        for start in range(0, len(pieces), _BATCH):
            if cancel is not None and cancel.is_set():
                self.delete_document(doc_id)               # no half-saved document
                return 0
            batch = pieces[start:start + _BATCH]
            vectors = self._embedder.embed_texts([text for _, text in batch], batch_size=_BATCH)
            self._client.upsert(self.COLLECTION, wait=True, points=[
                PointStruct(id=random.getrandbits(63),
                            vector={"dense": vec, "terms": terms.sparse(text)},
                            payload={"text": text, "source": source, "kind": kind, "where": where,
                                     "doc_id": doc_id, "path": path, "timestamp": ts})
                for (where, text), vec in zip(batch, vectors)])
            stored += len(batch)
            if progress:
                progress(100 * stored / len(pieces), f"{stored} de {len(pieces)} partes")
        return stored

    def ingest(self, text: str, source_name: str = "", chunk_mode: str = "sentence",
               chunk_size: int | None = None, chunk_overlap: int | None = None) -> int:
        """Pasted text (Base tab). Returns how many pieces were saved."""
        if not self.available or not text.strip():
            return 0
        try:
            return self._store_pieces(doc_id_for("texto:" + source_name), source_name, "texto", [("", text)])
        except Exception as e:
            log.warning(f"[KB] Ingestion failed: {e}")
            return 0

    def ingest_document(self, path: str | Path, progress=None, cancel: threading.Event | None = None) -> int:
        """A chosen file. Raises documents.Unreadable with the message for the person."""
        path = Path(path).resolve()
        sections = documents.read(path)
        return self._store_pieces(doc_id_for(str(path)), path.name, documents.kind_of(path), sections,
                                  progress, cancel, path=str(path))

    # ── searching ────────────────────────────────────────────────────────────

    def search_hits(self, query: str, query_vector: list[float] | None = None,
                    top_k: int | None = None, score_min: float | None = None) -> list[dict]:
        """Pieces by meaning + exact word, fused by DBSF. The minimum score is a gate on the BEST
        piece (is the question about the documents at all?); when it opens, the top pieces go (only the
        first ones when the best is weak).
        Cutting each piece by its own score dropped right answers ranked 2nd or 3rd: DBSF scores
        are relative to the candidates, so a fixed cut does not hold across bases (2026-10-31)."""
        if not self.available or not query.strip():
            return []
        top_k = top_k if top_k is not None else CONFIG.kb_top_k
        score_min = score_min if score_min is not None else CONFIG.kb_score_min
        try:
            vector = query_vector if query_vector is not None else self._embedder.embed_query(query)
            points = self._client.query_points(
                self.COLLECTION,
                prefetch=[Prefetch(query=vector, using="dense", limit=_PREFETCH),
                          Prefetch(query=terms.sparse(query), using="terms", limit=_PREFETCH)],
                query=FusionQuery(fusion=Fusion.DBSF), limit=top_k, with_payload=True).points
            if points and points[0].score < CONFIG.kb_strong_score:
                points = points[:CONFIG.kb_weak_top_k]
            log.info("[KB] best %.3f (gate %.2f) → %s", points[0].score if points else 0, score_min,
                     [label(p.payload) for p in points] if points and points[0].score >= score_min else "nothing")
            if not points or points[0].score < score_min:
                return []
            return [{**p.payload, "score": p.score} for p in points if p.payload]
        except Exception as e:
            log.warning(f"[KB] search error: {e}")
            return []

    def search(self, query: str, query_vector: list[float] | None = None, top_k: int | None = None,
               score_min: float | None = None) -> list[str]:
        """Pieces with their origin label, as the agent shows them to the model."""
        return [f"[{label(h)}] {h['text']}" for h in self.search_hits(query, query_vector, top_k, score_min)]

    # ── listing and removing ─────────────────────────────────────────────────

    def count(self) -> int:
        if not self.available:
            return 0
        try:
            return self._client.get_collection(self.COLLECTION).points_count or 0
        except Exception:
            return 0

    def list_all(self, n: int = 100_000) -> list[dict]:
        if not self.available:
            return []
        try:
            points, _ = self._client.scroll(self.COLLECTION, limit=n, with_payload=True, with_vectors=False)
            return [{"id": p.id, **p.payload} for p in points if p.payload]
        except Exception:
            return []

    def list_documents(self) -> list[dict]:
        """[{doc_id, source, kind, count, ts}] — most recent first."""
        docs: dict[str, dict] = {}
        for item in self.list_all():
            d = docs.setdefault(item.get("doc_id", item.get("source", "")), {
                "doc_id": item.get("doc_id", ""), "source": item.get("source", ""),
                "kind": item.get("kind", "texto"), "count": 0, "ts": item.get("timestamp", "")})
            d["count"] += 1
        return sorted(docs.values(), key=lambda d: d["ts"], reverse=True)

    def pieces_of(self, doc_id: str) -> list[dict]:
        return [i for i in self.list_all() if i.get("doc_id") == doc_id]

    def delete_document(self, doc_id: str) -> None:
        self._client.delete(self.COLLECTION, points_selector=Filter(
            must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]))

    def clear(self) -> int:
        if not self.available:
            return 0
        try:
            n = self.count()
            self._client.delete_collection(self.COLLECTION)
            self._ensure_collection()
            return n
        except Exception:
            return 0
