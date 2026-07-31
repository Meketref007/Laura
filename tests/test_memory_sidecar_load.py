import json

from shopee_agent.vector_store import InMemoryVectorStore
from shopee_agent.decision_memory import MemoryLayer


def test_memory_loads_vectors_sidecar(tmp_path):
    vectors_path = tmp_path / "vectors.jsonl"
    # create a sidecar with two records
    recs = [
        {"decision_id": "d1", "vector": [0.1] * 8, "metadata": {"rule_id": "r1"}},
        {"decision_id": "d2", "vector": [0.2] * 8, "metadata": {"rule_id": "r2"}},
    ]
    vectors_path.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")

    store = InMemoryVectorStore(dim=8)
    _mem = MemoryLayer(path=str(tmp_path / "outcomes.jsonl"), vector_store=store, vectors_path=str(vectors_path))

    # After initialization, vectors should be loaded into the store
    assert "d1" in store._vectors
    assert "d2" in store._vectors
    assert store.dim == 8
    assert store._meta.get("d1") == {"rule_id": "r1"}
