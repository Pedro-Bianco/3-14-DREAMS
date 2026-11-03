"""Term vectors for exact-word search (contract numbers, names, codes).

The dense vector finds meaning ("multa por atraso" ↔ "penalidade por mora") but ties on codes:
"2024-0815" and "2024-0816" scored 0.859 both (measured 2026-11-01). A sparse vector of the words,
with the IDF computed by Qdrant itself, separates them (34.0 × 16.5) with no extra model.
"""

import re
import unicodedata
import zlib

from qdrant_client.models import SparseVector

_WORD = re.compile(r"[a-z0-9]+(?:[-./][a-z0-9]+)*")


def tokens(text: str) -> list[str]:
    """Lowercase, no accents; codes like "2024-0815" kept whole AND split into their parts."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    words = _WORD.findall(plain)
    parts = [p for w in words for p in re.split(r"[-./]", w) if p and p != w]
    return words + parts


def sparse(text: str) -> SparseVector:
    """Term frequencies keyed by a stable hash of each token (same index on every run)."""
    counts: dict[int, float] = {}
    for token in tokens(text):
        index = zlib.crc32(token.encode()) & 0x7FFFFFFF
        counts[index] = counts.get(index, 0.0) + 1.0
    return SparseVector(indices=list(counts), values=list(counts.values()))
