from __future__ import annotations

import math
from typing import Any


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


class VectorStore:
    """Simple pluggable vector store interface."""

    def index(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        raise NotImplementedError()

    def query(self, vector: list[float], top_k: int = 5) -> list[tuple[str, float, dict[str, Any] | None]]:
        raise NotImplementedError()


class InMemoryVectorStore(VectorStore):
    """Lightweight in-memory vector store using cosine similarity."""

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim
        self._vectors: dict[str, list[float]] = {}
        self._meta: dict[str, dict[str, Any] | None] = {}

    def index(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        if self.dim is None:
            self.dim = len(vector)
        if len(vector) != self.dim:
            # Skip mismatched vectors instead of crashing
            return
        self._vectors[doc_id] = list(vector)
        self._meta[doc_id] = metadata

    def query(self, vector: list[float], top_k: int = 5) -> list[tuple[str, float, dict[str, Any] | None]]:
        if self.dim is None:
            return []
        if len(vector) != self.dim:
            return []

        q_norm = _norm(vector)
        if q_norm == 0:
            return []

        results: list[tuple[str, float, dict[str, Any] | None]] = []
        for doc_id, vec in self._vectors.items():
            denom = q_norm * _norm(vec)
            if denom == 0:
                score = 0.0
            else:
                score = _dot(vector, vec) / denom
            results.append((doc_id, float(score), self._meta.get(doc_id)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


def simple_text_to_vector(text: str, dim: int = 128) -> list[float]:
    """Deterministic fallback embedder: map sha256 digest to floats in [-1,1].

    Placed here so other modules (decision execution) can reuse the same
    lightweight embedder without importing CLI-specific helpers.
    """
    import hashlib

    h = hashlib.sha256(text.encode("utf-8")).digest()
    bys = (h * ((dim // len(h)) + 1))[:dim]
    vec = [((b / 255.0) * 2.0 - 1.0) for b in bys]
    return vec
