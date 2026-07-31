import json
import pytest

from shopee_agent.decision_memory import MemoryLayer


def make_sidecar(tmp_path, dim=8):
    vectors_path = tmp_path / "vectors.jsonl"
    recs = [
        {"decision_id": "r1", "vector": [0.1] * dim, "metadata": {"rule_id": "r1"}},
        {"decision_id": "r2", "vector": [0.2] * dim, "metadata": {"rule_id": "r2"}},
    ]
    vectors_path.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    return vectors_path


def test_reindex_to_memory_backend(tmp_path):
    vectors_path = make_sidecar(tmp_path, dim=8)
    mem = MemoryLayer(path=str(tmp_path / "outcomes.jsonl"), vector_store=None, vectors_path=str(vectors_path))
    store = mem.reindex_to_backend(backend="memory", dim=8)
    assert hasattr(store, "_vectors")
    assert "r1" in store._vectors and "r2" in store._vectors


@pytest.mark.skipif(pytest.importorskip("faiss", reason="faiss not available") is None, reason="faiss not available")
def test_reindex_to_faiss_backend(tmp_path):
    vectors_path = make_sidecar(tmp_path, dim=8)
    mem = MemoryLayer(path=str(tmp_path / "outcomes.jsonl"), vector_store=None, vectors_path=str(vectors_path))
    store = mem.reindex_to_backend(backend="faiss", dim=8, index_path=str(tmp_path / "faiss.idx"), meta_path=str(tmp_path / "faiss.meta.json"))
    # If Faiss is available, store should have id map or meta
    assert store is not None
