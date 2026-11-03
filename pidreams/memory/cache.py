import datetime as dt
from collections import deque

from pidreams.memory.embedder import FastEmbedManager


class SemanticCache:
    """Recent replies for near-identical questions. Valid only on the day they were given:
    "que dia é hoje?" or "o que tenho amanhã?" answered yesterday would be wrong today."""

    THRESHOLD = 0.95
    MAX_SIZE = 20

    def __init__(self, embedder: FastEmbedManager):
        self._embedder = embedder
        self._cache: deque[tuple[list, str, dt.date]] = deque(maxlen=self.MAX_SIZE)

    def get(self, query: str) -> str | None:
        q_vec = self._embedder.embed_query(query)
        today = dt.date.today()
        for vec, answer, day in self._cache:
            if day == today and self._embedder.similarity(q_vec, vec) >= self.THRESHOLD:
                return answer
        return None

    def clear(self):
        self._cache.clear()

    def put(self, query: str, answer: str):
        q_vec = self._embedder.embed_query(query)
        self._cache.append((q_vec, answer, dt.date.today()))
