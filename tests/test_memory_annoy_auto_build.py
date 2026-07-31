import os
import tempfile

from datetime import datetime, timezone
import importlib.util
import pytest

if importlib.util.find_spec("annoy") is None:
    pytest.skip("annoy not installed; skipping Annoy integration tests", allow_module_level=True)

from shopee_agent.vector_store_annoy import AnnoyVectorStore
from shopee_agent.decision_memory import MemoryLayer, DecisionOutcome


def test_memory_layer_triggers_annoy_build_and_persists_meta():
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "test_auto.ann")
    meta_path = os.path.join(tmpdir, "test_auto_meta.json")
    outcomes_path = os.path.join(tmpdir, "outcomes.jsonl")

    store = AnnoyVectorStore(dim=3, index_path=index_path, meta_path=meta_path, n_trees=5)
    mem = MemoryLayer(path=outcomes_path, vector_store=store, vectors_path=os.path.join(tmpdir, "vectors.jsonl"))

    o = DecisionOutcome(decision_id="d1", rule_id="r1", executed_at=datetime.now(timezone.utc), outcome_type="success", metadata={})
    vec = [1.0, 0.0, 0.0]

    mem.remember_outcome_with_vector(o, vector=vec)

    # Annoy index file and meta sidecar should exist after remembering
    assert os.path.exists(index_path)
    assert os.path.exists(meta_path)

    # Query should return the stored doc
    res = store.query([1.0, 0.0, 0.0], top_k=1)
    assert res and res[0][0] == "d1"
