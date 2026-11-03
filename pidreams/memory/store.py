import logging
import random
from datetime import datetime, timezone

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter,
    HnswConfigDiff, MatchValue, OptimizersConfigDiff,
    PointStruct, VectorParams,
)

from pidreams.core.config import CONFIG
from pidreams.memory.embedder import FastEmbedManager

log = logging.getLogger(__name__)


class LTMStore:
    COLLECTION = "pi_dreams_ltm"

    def __init__(self):
        self.available = False
        self._client = None
        self._embedder = None
        try:
            self._client = QdrantClient(path=CONFIG.qdrant_path)
            self._embedder = FastEmbedManager(CONFIG.ltm_embedding_model)
            self._ensure_collection()
            self.available = True
            log.info(f"[LTM] Qdrant (local) connected — collection '{self.COLLECTION}'")
        except Exception as e:
            # Embedded Qdrant holds an exclusive lock on the folder. Release it
            # when loading the embedding fails, so the KB can open the same
            # database later.
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
            log.warning(f"[LTM] Qdrant unavailable: {e}")

    def _ensure_collection(self):
        existing = {c.name for c in self._client.get_collections().collections}
        if self.COLLECTION not in existing:
            self._client.create_collection(
                collection_name=self.COLLECTION,
                vectors_config=VectorParams(
                    size=self._embedder.vector_size,
                    distance=Distance.COSINE,
                ),
                optimizers_config=OptimizersConfigDiff(indexing_threshold=100),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
            )

    def _query_points(
        self,
        vec: list,
        top_k: int,
        score_min: float,
        with_filter: bool = False,
    ) -> list:
        query_filter = Filter(
            must=[FieldCondition(key="tag_projeto", match=MatchValue(value="pi_dreams"))]
        ) if with_filter else None
        return self._client.query_points(
            collection_name=self.COLLECTION,
            query=vec,
            limit=top_k,
            score_threshold=score_min,
            query_filter=query_filter,
            with_payload=True,
        ).points

    def _scroll_items(self, n: int, include_id: bool = False) -> list[dict]:
        points, _ = self._client.scroll(
            collection_name=self.COLLECTION,
            limit=max(n, 200),
            with_payload=True,
            with_vectors=False,
        )
        items = [
            {
                **({"id": p.id} if include_id else {}),
                "text": p.payload.get("text", ""),
                "ts": p.payload.get("timestamp", ""),
            }
            for p in points if p.payload
        ]
        items.sort(key=lambda x: x["ts"], reverse=True)
        return items[:n]

    def search(self, query: str, top_k: int = 3, score_min: float = 0.55,
               query_vector: list[float] | None = None) -> list[str]:
        """query_vector: the turn's question vector, computed once for memory and documents."""
        if not self.available:
            return []
        try:
            vec = query_vector if query_vector is not None else self._embedder.embed_query(query)
            results = self._query_points(vec, top_k, score_min, with_filter=True)
            return [r.payload["text"] for r in results if r.payload]
        except Exception as e:
            log.warning(f"[LTM] search error: {e}")
            return []

    def profile(self, n: int = 10) -> list[str]:
        """Name, how to address the user, preferences and instructions: always in the conversation
        (Vertex AI Memory Bank also loads the profile at the start, besides similarity search)."""
        if not self.available:
            return []
        try:
            points, _ = self._client.scroll(
                collection_name=self.COLLECTION, limit=200, with_payload=True, with_vectors=False,
                scroll_filter=Filter(must=[FieldCondition(key="kind", match=MatchValue(value="perfil"))]))
            points = sorted((p for p in points if p.payload), key=lambda p: p.payload.get("timestamp", ""), reverse=True)
            return [p.payload["text"] for p in points[:n]]
        except Exception as e:
            log.warning(f"[LTM] profile error: {e}")
            return []

    def count(self) -> int:
        if not self.available:
            return 0
        try:
            return self._client.get_collection(self.COLLECTION).points_count or 0
        except Exception:
            return 0

    def list_recent(self, n: int = 15) -> list[dict]:
        if not self.available:
            return []
        try:
            return self._scroll_items(n)
        except Exception:
            return []

    def list_all(self, n: int = 500) -> list[dict]:
        if not self.available:
            return []
        try:
            return self._scroll_items(n, include_id=True)
        except Exception:
            return []

    def list_for_graph(self, n: int = 500) -> list[dict]:
        """Everything the memory graph draws: id, text, kind, topic, date and the stored vector."""
        if not self.available:
            return []
        try:
            points, _ = self._client.scroll(self.COLLECTION, limit=n, with_payload=True, with_vectors=True)
            return [{"id": p.id, "text": p.payload.get("text", ""), "kind": p.payload.get("kind", "fato"),
                     "topic": p.payload.get("topic"), "ts": p.payload.get("timestamp", ""), "vector": p.vector}
                    for p in points if p.payload]
        except Exception as e:
            log.warning(f"[LTM] graph list error: {e}")
            return []

    def untagged(self, n: int = 500) -> list[dict]:
        """Memories still without a topic: [{id, text, kind}]."""
        if not self.available:
            return []
        try:
            points, _ = self._client.scroll(self.COLLECTION, limit=n, with_payload=True, with_vectors=False)
            return [{"id": p.id, "text": p.payload.get("text", ""), "kind": p.payload.get("kind", "fato")}
                    for p in points if p.payload and not p.payload.get("topic")]
        except Exception as e:
            log.warning(f"[LTM] untagged error: {e}")
            return []

    def set_topics(self, topics: dict) -> None:
        """{point id: topic}. Points deleted meanwhile are skipped by Qdrant."""
        by_topic: dict[str, list] = {}
        for point_id, topic in topics.items():
            by_topic.setdefault(topic, []).append(point_id)
        for topic, ids in by_topic.items():
            self._client.set_payload(self.COLLECTION, payload={"topic": topic}, points=ids)

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

    def delete_one(self, point_id) -> bool:
        if not self.available:
            return False
        try:
            from qdrant_client.models import PointIdsList
            self._client.delete(
                collection_name=self.COLLECTION,
                points_selector=PointIdsList(points=[point_id]),
            )
            return True
        except Exception:
            return False

    def search_text_gui(self, query: str, top_k: int = 15, score_min: float = 0.40) -> list[dict]:
        if not self.available:
            return []
        try:
            vec = self._embedder.embed_query(query)
            results = self._query_points(vec, top_k, score_min)
            return [
                {"id": r.id, "text": r.payload.get("text", ""),
                 "ts": r.payload.get("timestamp", ""), "score": r.score}
                for r in results if r.payload
            ]
        except Exception as e:
            log.warning(f"[LTM] search_gui error: {e}")
            return []

    def search_candidates(self, text: str, threshold: float, top_k: int = 5) -> list[dict]:
        if not self.available:
            return []
        try:
            vec = self._embedder.embed_text(text)
            results = self._query_points(vec, top_k, threshold)
            return [
                {"id": r.id, "text": r.payload.get("text", ""), "score": r.score}
                for r in results if r.payload
            ]
        except Exception as e:
            log.warning(f"[LTM] search_candidates error: {e}")
            return []

    def upsert(self, text: str, project_tag: str = "pi_dreams", dedup_threshold: float = 0.96,
               kind: str = "fato") -> bool:
        """kind: "perfil" (name, how to call the user, preferences, instructions) or "fato".
        Memories saved before v0.4.0 have no kind and count as "fato"."""
        if not self.available:
            return False
        try:
            vec = self._embedder.embed_text(text)
            dupes = self._query_points(vec, top_k=1, score_min=dedup_threshold)
            if dupes:
                log.info(f"[LTM] Duplicate ignored ({dupes[0].score:.2f}): {text[:60]}")
                return False
            self._client.upsert(
                collection_name=self.COLLECTION,
                points=[PointStruct(
                    id=random.getrandbits(63),
                    vector=vec,
                    payload={
                        "text": text,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tag_projeto": project_tag,
                        "kind": kind,
                    },
                )],
                wait=True,
            )
            return True
        except Exception as e:
            log.warning(f"[LTM] Save failed: {e}")
            return False
