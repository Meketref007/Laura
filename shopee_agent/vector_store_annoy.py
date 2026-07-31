from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

try:
    from annoy import AnnoyIndex
except Exception:  # pragma: no cover - optional dependency
    AnnoyIndex = None  # type: ignore

from .vector_store import VectorStore


class AnnoyVectorStore(VectorStore):
    """Persistent Annoy-backed vector store.

    This is a lightweight production-ready adapter that persists the Annoy
    index to disk along with a JSON sidecar for metadata and id mappings.
    """

    def __init__(
        self,
        dim: int,
        index_path: str | None = None,
        meta_path: str | None = None,
        metric: str = "angular",
        n_trees: int = 10,
        background_build: bool = False,
        build_interval: int = 60,
    ) -> None:
        if AnnoyIndex is None:
            raise RuntimeError("annoy package is required for AnnoyVectorStore")

        self.dim = dim
        self.index_path = index_path
        self.meta_path = meta_path
        self.metric = metric
        self.n_trees = n_trees

        self._annoy: AnnoyIndex | None = None
        self._id_map: dict[str, int] = {}
        self._rev_map: dict[int, str] = {}
        self._vectors: dict[int, list[float]] = {}
        self._meta: dict[str, dict[str, Any] | None] = {}
        self._next_id = 0
        self._dirty = True
        self._background_build = background_build
        self._build_interval = build_interval
        self._stop_event: threading.Event | None = None
        self._bg_thread: threading.Thread | None = None

        if self.meta_path and os.path.exists(self.meta_path):
            try:
                with open(self.meta_path) as f:
                    data = json.load(f)
                self._id_map = data.get("id_map", {})
                self._meta = data.get("meta", {})
                # reconstruct rev map and next id
                self._rev_map = {int(v): k for k, v in self._id_map.items()}
                if self._rev_map:
                    self._next_id = max(self._rev_map.keys()) + 1
            except Exception:
                # ignore corrupt meta sidecar
                pass

        # Try to load existing Annoy index file if present
        if self.index_path and os.path.exists(self.index_path):
            try:
                ai = AnnoyIndex(self.dim, self.metric)
                ai.load(self.index_path)
                self._annoy = ai
                # Annoy index loaded; we consider it not dirty
                self._dirty = False
            except Exception:
                # ignore load errors
                pass

        # Start background builder if requested
        if self._background_build:
            try:
                self._stop_event = threading.Event()
                self._bg_thread = threading.Thread(target=self._background_builder, daemon=True)
                self._bg_thread.start()
            except Exception:
                self._stop_event = None
                self._bg_thread = None

    def _ensure_index(self) -> None:
        if self._annoy is not None and not self._dirty:
            return

        self._annoy = AnnoyIndex(self.dim, self.metric)
        for idx, vec in self._vectors.items():
            self._annoy.add_item(idx, vec)

        if self._vectors:
            self._annoy.build(self.n_trees)

        # persist index file if configured
        if self.index_path and self._annoy is not None:
            try:
                self._annoy.save(self.index_path)
            except Exception:
                pass

        self._dirty = False

    def _background_builder(self) -> None:
        if self._stop_event is None:
            return
        while not self._stop_event.is_set():
            try:
                if self._dirty:
                    try:
                        self._ensure_index()
                    except Exception:
                        pass
                    try:
                        self._save_meta()
                    except Exception:
                        pass
                time.sleep(self._build_interval)
            except Exception:
                # Avoid killing the thread on unexpected errors; sleep briefly
                time.sleep(min(5, self._build_interval))

    def stop_background(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._bg_thread is not None:
            try:
                self._bg_thread.join(timeout=2)
            except Exception:
                pass

    def _save_meta(self) -> None:
        if not self.meta_path:
            return
        data = {"id_map": self._id_map, "meta": self._meta}
        try:
            with open(self.meta_path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def index(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        if len(vector) != self.dim:
            raise ValueError("vector dimensionality mismatch")

        if doc_id in self._id_map:
            idx = int(self._id_map[doc_id])
        else:
            idx = self._next_id
            self._id_map[doc_id] = idx
            self._rev_map[idx] = doc_id
            self._next_id += 1

        self._vectors[idx] = list(vector)
        self._meta[doc_id] = metadata
        self._dirty = True
        self._save_meta()

    def query(self, vector: list[float], top_k: int = 5) -> list[tuple[str, float, dict[str, Any] | None]]:
        if len(vector) != self.dim:
            raise ValueError("vector dimensionality mismatch")

        self._ensure_index()

        if not self._vectors:
            return []

        # Annoy supports returning distances; convert angular distance to cosine-like score
        try:
            ids, dists = self._annoy.get_nns_by_vector(vector, top_k, include_distances=True)  # type: ignore[arg-type]
        except TypeError:
            ids = self._annoy.get_nns_by_vector(vector, top_k)  # type: ignore[arg-type]
            dists = [0.0 for _ in ids]

        results: list[tuple[str, float, dict[str, Any] | None]] = []
        for idx, dist in zip(ids, dists):
            doc_id = self._rev_map.get(int(idx), str(idx))
            # angular distance in Annoy approx maps to similarity via (1 - dist/2)
            score = 1.0 - (dist / 2.0) if isinstance(dist, (int, float)) else 0.0
            results.append((doc_id, float(score), self._meta.get(doc_id)))

        return results
