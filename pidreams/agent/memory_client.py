import asyncio

from pidreams.memory.cache import SemanticCache
from pidreams.memory.store import LTMStore
from pidreams.memory.worker import MemoryWorker
from pidreams.core.config import CONFIG


class MemoryClient:
    """Single access point to the LTM: store (Qdrant), semantic cache and worker."""

    def __init__(self, store: LTMStore | None = None, on_store=None):
        self._store = store if store is not None else LTMStore()
        if self._store.available:
            self._cache = SemanticCache(self._store._embedder)
            self._worker = MemoryWorker(self._store, on_store=on_store)
        else:
            self._cache = None
            self._worker = None

    @property
    def available(self) -> bool:
        return self._store.available

    def embed_query(self, query: str) -> list[float] | None:
        """The turn's question vector: computed once, used by the memory and by the documents
        (each e5 vector costs ~300 ms on the CPU)."""
        return self._store._embedder.embed_query(query) if self.available else None

    async def search(self, query: str, query_vector: list[float] | None = None) -> list[str]:
        if not self.available:
            return []
        return await asyncio.to_thread(
            self._store.search, query, CONFIG.ltm_top_k, CONFIG.ltm_score_min, query_vector
        )

    def profile(self) -> list[str]:
        return self._store.profile() if self.available else []

    def cache_get(self, query: str) -> str | None:
        if self._cache is None:
            return None
        return self._cache.get(query)

    def cache_clear(self):
        if self._cache is not None:
            self._cache.clear()

    def cache_put(self, query: str, answer: str):
        if self._cache is not None:
            self._cache.put(query, answer)

    def submit_to_worker(self, session_buffer: list[dict]):
        if self._worker is not None:
            self._worker.submit(session_buffer)

    def drain(self, timeout: float) -> None:
        if self._worker is not None:
            self._worker.drain(timeout)
