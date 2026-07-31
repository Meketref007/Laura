"""
Memory layer for Decision Engine (Phase 35)

Provides:
- `DecisionOutcome` dataclass for recording execution outcomes
- `MemoryLayer` that stores outcomes in JSONL and offers simple analytics

This is intentionally simple (Phase 35 MVP): a JSONL-backed store with
basic aggregation and similarity functions. Phase 36+ can replace this
with a vector DB or more advanced storage.
"""

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import DECISION_OUTCOMES, DECISION_VECTORS


@dataclass
class DecisionOutcome:
    decision_id: str
    rule_id: str
    executed_at: datetime | None = None
    outcome_type: str = "executed"  # executed | success | partial | failure | reverted
    impact_realized: float | None = None  # Actual measured impact (e.g., margin delta)
    margin_change: float | None = None
    revenue_change: float | None = None
    satisfaction_change: float | None = None
    reversals: int = 0
    feedback: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["executed_at"] = self.executed_at.isoformat() if self.executed_at else None
        return d


class MemoryLayer:
    """Simple JSONL-backed memory store for decision outcomes.

    Supports optional semantic vector integration via a pluggable `vector_store`.
    If provided, callers may pass a `vector` to `remember_outcome` and the
    vector will be indexed alongside outcome metadata.
    """

    def __init__(self, path: str = str(DECISION_OUTCOMES), vector_store: Any | None = None, vectors_path: str = str(DECISION_VECTORS)):
        self.path = Path(path)
        self.vectors_path = Path(vectors_path)
        self._cache: list[DecisionOutcome] = []
        self._by_id: dict[str, DecisionOutcome] = {}
        self.vector_store = vector_store
        logging.getLogger(__name__).debug("MemoryLayer init | path=%s vectors_path=%s has_vector_store=%s", str(self.path), str(self.vectors_path), bool(self.vector_store))
        # Ensure parent dir exists
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Load existing outcomes into memory
        self._load()
        # Load any persisted sidecar vectors into the provided vector store
        try:
            self._load_vectors_sidecar()
        except Exception:
            pass

    def _append_vector_record(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        try:
            self.vectors_path.parent.mkdir(parents=True, exist_ok=True)
            rec = {
                "decision_id": doc_id,
                "vector": list(vector),
                "metadata": metadata or {},
            }
            with self.vectors_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            # Best-effort: do not fail the flow if we can't persist vectors
            pass

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        executed_at = None
                        if obj.get("executed_at"):
                            try:
                                executed_at = datetime.fromisoformat(obj["executed_at"])  # best-effort
                            except Exception:
                                executed_at = None
                        outcome = DecisionOutcome(
                            decision_id=obj.get("decision_id", ""),
                            rule_id=obj.get("rule_id", ""),
                            executed_at=executed_at,
                            outcome_type=obj.get("outcome_type", "executed"),
                            impact_realized=obj.get("impact_realized"),
                            margin_change=obj.get("margin_change"),
                            revenue_change=obj.get("revenue_change"),
                            satisfaction_change=obj.get("satisfaction_change"),
                            reversals=int(obj.get("reversals", 0)),
                            feedback=obj.get("feedback"),
                            metadata=obj.get("metadata", {}),
                        )
                        self._cache.append(outcome)
                        self._by_id[outcome.decision_id] = outcome
                    except json.JSONDecodeError:
                        continue
        except Exception:
            # Non-fatal: memory will start empty
            self._cache = []

    def _load_vectors_sidecar(self) -> None:
        """Load persisted vectors from the sidecar `vectors_path` into the
        configured `vector_store` (if present). This ensures that when a
        `MemoryLayer` is constructed with an already-populated sidecar, the
        provided `vector_store` becomes immediately usable for queries.
        """
        p = Path(self.vectors_path)
        if not p.exists():
            logging.getLogger(__name__).debug("No vectors sidecar found at %s", str(p))
            return
        if self.vector_store is None:
            logging.getLogger(__name__).warning("Vectors sidecar present but no vector_store configured; skipping load: %s", str(p))
            return
        try:
            loaded = 0
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        doc_id = rec.get("decision_id")
                        vector = rec.get("vector")
                        meta = rec.get("metadata", {})
                        if doc_id and vector is not None:
                            try:
                                self.vector_store.index(doc_id, vector, metadata=meta)
                                loaded += 1
                            except Exception:
                                logging.getLogger(__name__).exception("Failed to index vector for doc_id=%s", doc_id)
                                # best-effort: skip problematic records
                                continue
                    except Exception:
                        logging.getLogger(__name__).exception("Failed to parse vector sidecar line")
                        continue
            logging.getLogger(__name__).info("Loaded %d vectors from sidecar %s", loaded, str(p))
        except Exception:
            logging.getLogger(__name__).exception("Unexpected error loading vectors sidecar %s", str(p))
            pass

    def remember_outcome(self, outcome: DecisionOutcome) -> None:
        """Record an outcome to the JSONL store and in-memory cache."""
        # Append to file
        try:
            with open(self.path, "a") as f:
                f.write(json.dumps(outcome.to_dict()) + "\n")
        except Exception:
            # Best-effort: ignore write failures
            pass

        # Update in-memory cache
        self._cache.append(outcome)
        self._by_id[outcome.decision_id] = outcome

    def remember_outcome_with_vector(self, outcome: DecisionOutcome, vector: list[float] | None = None) -> None:
        """Convenience: remember an outcome and optionally index its vector in the vector_store."""
        self.remember_outcome(outcome)
        if self.vector_store is not None and vector is not None:
            try:
                meta = {"rule_id": outcome.rule_id, "decision_id": outcome.decision_id, **(outcome.metadata or {})}
                self.vector_store.index(outcome.decision_id, vector, metadata=meta)
                # Persist vector to sidecar file for durability and future re-index
                try:
                    self._append_vector_record(outcome.decision_id, vector, metadata=meta)
                except Exception:
                    pass
                # If the vector store supports building/persisting an on-disk index
                # (e.g., Annoy), attempt to build and persist immediately so that
                # subsequent search CLI calls see the new vector without requiring
                # a separate reindex operation.
                try:
                    if hasattr(self.vector_store, "_ensure_index"):
                        try:
                            self.vector_store._ensure_index()
                        except Exception:
                            pass
                    if hasattr(self.vector_store, "_save_meta"):
                        try:
                            self.vector_store._save_meta()
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                pass

    def list_outcomes(self, limit: int = 100) -> list[DecisionOutcome]:
        """Return recent outcomes (most recent last)."""
        return list(self._cache[-limit:])

    def get_rule_effectiveness(self, rule_id: str) -> float:
        """Compute simple effectiveness score for a rule: success_rate.

        success = outcome_type == 'success'
        partial counts as 0.5 success. Others are failures.
        Returns value in [0.0, 1.0]. If no data, return 0.5 (neutral).
        """
        relevant = [o for o in self._cache if o.rule_id == rule_id]
        if not relevant:
            return 0.5

        score_sum = 0.0
        for o in relevant:
            if o.outcome_type == "success":
                score_sum += 1.0
            elif o.outcome_type == "partial":
                score_sum += 0.5
            else:
                score_sum += 0.0

        return score_sum / len(relevant)

    def rank_similar_decisions(self, current_signal: dict[str, Any], limit: int = 10) -> list[DecisionOutcome]:
        """Return outcomes with similar signal metrics. This is a heuristic:
        we match on `metric` or `rule_id` present in metadata.
        """
        metric = current_signal.get("metric") or current_signal.get("type")
        results = []
        for o in self._cache:
            # Score 2 for rule match, 1 for metric in metadata
            score = 0
            if metric and o.metadata.get("metric") == metric:
                score += 1
            if o.rule_id and current_signal.get("rule_id") and o.rule_id == current_signal.get("rule_id"):
                score += 2
            if score > 0:
                results.append((score, o))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def semantic_query(self, vector: list[float], top_k: int = 10) -> list[dict[str, Any]]:
        """Query the optional vector_store and return list of {outcome, score} dicts.

        If no vector_store is configured, returns an empty list.
        """
        if self.vector_store is None:
            return []
        try:
            results = self.vector_store.query(vector, top_k=top_k)
        except Exception:
            return []

        out: list[dict[str, Any]] = []
        for doc_id, score, meta in results:
            outcome = self._by_id.get(doc_id)
            out.append({"decision_id": doc_id, "score": score, "outcome": outcome, "meta": meta})
        return out

    def predict_outcome_for_rule(self, rule_id: str) -> float:
        """Predict expected impact (mean of impact_realized) for a rule.
        Returns 0.0 if unknown.
        """
        relevant = [o for o in self._cache if o.rule_id == rule_id and o.impact_realized is not None]
        if not relevant:
            return 0.0
        vals = [o.impact_realized for o in relevant]
        return sum(vals) / len(vals)

    def predict_outcome_for_decision(self, decision: Any) -> float:
        """Predict expected impact for a decision based on similar past outcomes.
        
        Uses rule_id matching and metadata similarity heuristics.
        Returns mean impact_realized or 0.0 if no data.
        """
        relevant = [o for o in self._cache if o.rule_id == decision.rule_id and o.impact_realized is not None]
        if not relevant:
            return 0.0
        vals = [o.impact_realized for o in relevant]
        # Weight recent outcomes higher (linear decay over last 50)
        weighted = 0.0
        total_w = 0.0
        for i, v in enumerate(reversed(vals[-50:])):
            w = 1.0 + i * 0.02  # slight recency bias
            weighted += v * w
            total_w += w
        return weighted / total_w if total_w else 0.0

    def decay_old_outcomes(self, max_age_days: int = 90) -> int:
        """Remove outcomes older than max_age_days from memory cache.
        
        Returns count of removed outcomes.
        """
        cutoff = datetime.now(UTC)
        if hasattr(cutoff, 'timestamp'):
            pass
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        before = len(self._cache)
        self._cache = [o for o in self._cache if o.executed_at and o.executed_at >= cutoff]
        removed = before - len(self._cache)
        for oid in list(self._by_id.keys()):
            if oid not in {o.decision_id for o in self._cache}:
                self._by_id.pop(oid, None)
        return removed

    def reindex_to_backend(self, backend: str = "memory", dim: int = 128, index_path: str | None = None, meta_path: str | None = None):
        """Rebuild a vector backend from the vectors sidecar file.

        Supported backends:
        - "memory": returns an `InMemoryVectorStore` populated from the sidecar
        - "faiss": returns a `FaissVectorStore` (requires `faiss` installed)

        The method sets `self.vector_store` to the newly built store and
        returns the store instance.
        """
        store = None
        logging.getLogger(__name__).info("Reindexing to backend=%s dim=%s index_path=%s", backend, dim, index_path)
        try:
            if backend == "memory":
                from .vector_store import InMemoryVectorStore

                store = InMemoryVectorStore(dim=dim)
            elif backend == "faiss":
                from .vector_store_faiss import FaissVectorStore

                store = FaissVectorStore(dim=dim, index_path=index_path, meta_path=meta_path)
            else:
                raise ValueError(f"unsupported backend: {backend}")

            p = Path(self.vectors_path)
            if not p.exists():
                # Nothing to index; return the empty store
                self.vector_store = store
                return store

            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        doc_id = rec.get("decision_id")
                        vector = rec.get("vector")
                        meta = rec.get("metadata", {})
                        if doc_id and vector is not None:
                            try:
                                store.index(doc_id, vector, metadata=meta)
                            except Exception:
                                # Best-effort: skip problematic records
                                continue
                    except Exception:
                        continue

            # Persist as active vector store
            self.vector_store = store
            logging.getLogger(__name__).info("Reindex complete; assigned vector_store=%s", type(store).__name__ if store else None)
            return store
        except Exception:
            logging.getLogger(__name__).exception("Error during reindex_to_backend")
            # On unexpected errors, do not crash callers
            return store


class DecisionRanker:
    """Ranking utilities for decision retrieval and comparison.
    
    Provides:
    - rank_by_similarity: find past decisions matching current signal
    - rank_by_outcome_quality: order by realized impact
    - decay_old_decisions: apply time-based decay weights
    """

    @staticmethod
    def rank_by_similarity(memory: MemoryLayer, current_signal: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        """Rank past decisions by similarity to current signal."""
        outcomes = memory.rank_similar_decisions(current_signal, limit=limit)
        return [{"decision_id": o.decision_id, "score": 1.0, "outcome": o} for o in outcomes]

    @staticmethod
    def rank_by_outcome_quality(memory: MemoryLayer, rule_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Rank decisions by best realized impact (highest margin_change)."""
        candidates = [o for o in memory._cache if o.impact_realized is not None]
        if rule_id:
            candidates = [o for o in candidates if o.rule_id == rule_id]
        candidates.sort(key=lambda o: o.impact_realized or 0.0, reverse=True)
        return [{"decision_id": o.decision_id, "score": o.impact_realized, "outcome": o} for o in candidates[:limit]]

    @staticmethod
    def decay_old_decisions(outcomes: list[DecisionOutcome], half_life_days: float = 30.0) -> list[dict[str, Any]]:
        """Apply time-based decay weight to outcomes. Recent = higher weight."""
        now = datetime.now(UTC)
        from datetime import timedelta
        half_life = timedelta(days=half_life_days).total_seconds()
        results = []
        for o in outcomes:
            if o.executed_at:
                age_seconds = (now - o.executed_at).total_seconds()
                weight = math.exp(-age_seconds / half_life)
            else:
                weight = 0.0
            results.append({"decision_id": o.decision_id, "weight": weight, "outcome": o})
        results.sort(key=lambda x: x["weight"], reverse=True)
        return results
