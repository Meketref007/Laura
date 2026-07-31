from __future__ import annotations

from typing import Any

try:
    import faiss
except Exception:  # pragma: no cover - optional dependency
    faiss = None  # type: ignore

from .vector_store import VectorStore


class FaissVectorStore(VectorStore):
    """Faiss-backed vector store adapter (optional dependency).

    This adapter is minimal: it supports indexing by incremental id mapping,
    building an index (IndexFlatIP) for cosine/inner-product similarity
    and querying the top-k results.
    """

    def __init__(self, dim: int, index_path: str | None = None, meta_path: str | None = None):
        if faiss is None:
            raise RuntimeError("faiss is required for FaissVectorStore")

        import json
        import os

        self.dim = dim
        self.index_path = index_path
        self.meta_path = meta_path
        self._id_map: dict[str, int] = {}
        self._rev_map: dict[int, str] = {}
        self._next_id = 0
        self._meta: dict[str, dict[str, Any] | None] = {}

        # Try to load existing index and meta mapping
        if self.index_path and os.path.exists(self.index_path):
            try:
                self._index = faiss.read_index(self.index_path)
            except Exception:
                self._index = faiss.IndexFlatIP(dim)
        else:
            self._index = faiss.IndexFlatIP(dim)

        if self.meta_path and os.path.exists(self.meta_path):
            try:
                with open(self.meta_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._id_map = data.get("id_map", {})
                # reconstruct rev map
                self._rev_map = {int(v): k for k, v in self._id_map.items()}
                if self._rev_map:
                    self._next_id = max(self._rev_map.keys()) + 1
                self._meta = data.get("meta", {})
            except Exception:
                pass

    def index(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        if len(vector) != self.dim:
            raise ValueError("vector dimensionality mismatch")

        if doc_id in self._id_map:
            idx = self._id_map[doc_id]
        else:
            idx = self._next_id
            self._id_map[doc_id] = idx
            self._rev_map[idx] = doc_id
            self._next_id += 1
        import json

        import numpy as np

        vec = np.array(vector, dtype="float32").reshape(1, -1)
        # Append vector to index
        try:
            self._index.add(vec)
        except Exception:
            # On unexpected error, recreate index and add
            self._index = faiss.IndexFlatIP(self.dim)
            self._index.add(vec)

        self._meta[doc_id] = metadata

        # Persist index and meta mapping if paths provided
        try:
            if self.index_path:
                faiss.write_index(self._index, self.index_path)
        except Exception:
            pass

        try:
            if self.meta_path:
                with open(self.meta_path, "w", encoding="utf-8") as fh:
                    json.dump({"id_map": self._id_map, "meta": self._meta}, fh)
        except Exception:
            pass

    def query(self, vector: list[float], top_k: int = 5) -> list[tuple[str, float, dict[str, Any] | None]]:
        if faiss is None:
            return []
        if len(vector) != self.dim:
            raise ValueError("vector dimensionality mismatch")

        import numpy as np

        q = np.array(vector, dtype="float32").reshape(1, -1)
        D, I = self._index.search(q, top_k)
        results: list[tuple[str, float, dict[str, Any] | None]] = []
        for dist, idx in zip(D[0].tolist(), I[0].tolist()):
            if idx < 0:
                continue
            doc_id = self._rev_map.get(idx, str(idx))
            # For IndexFlatIP, distances are inner products; treat as score
            score = float(dist)
            results.append((doc_id, score, self._meta.get(doc_id)))

        return results
