from datetime import datetime, timezone
from shopee_agent.decision_memory import DecisionOutcome, MemoryLayer
from shopee_agent.vector_store import InMemoryVectorStore


def test_memory_layer_with_vector_store(tmp_path):
    store = InMemoryVectorStore()
    out_path = tmp_path / "decision_outcomes.jsonl"
    vec_path = tmp_path / "decision_vectors.jsonl"
    mem = MemoryLayer(path=str(out_path), vector_store=store, vectors_path=str(vec_path))

    o1 = DecisionOutcome(
        decision_id="d1",
        rule_id="r1",
        executed_at=datetime.now(timezone.utc),
        outcome_type="success",
        impact_realized=1.0,
        metadata={"note": "first"},
    )
    o2 = DecisionOutcome(
        decision_id="d2",
        rule_id="r2",
        executed_at=datetime.now(timezone.utc),
        outcome_type="failure",
        impact_realized=0.0,
        metadata={"note": "second"},
    )

    mem.remember_outcome_with_vector(o1, vector=[1.0, 0.0])
    mem.remember_outcome_with_vector(o2, vector=[0.0, 1.0])

    results = mem.semantic_query([0.9, 0.1], top_k=2)
    assert len(results) >= 1
    assert results[0]["decision_id"] == "d1"
