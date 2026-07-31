from datetime import datetime, timezone

from shopee_agent.vector_store import InMemoryVectorStore
from shopee_agent.decision_memory import MemoryLayer
from shopee_agent.decision_engine import DecisionEngine, Decision, DecisionType, DecisionPriority, DecisionStatus, DecisionSignal


def test_execute_decision_indexes_vector_and_persists(tmp_path):
    vectors_path = tmp_path / "vectors.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"

    store = InMemoryVectorStore(dim=128)
    mem = MemoryLayer(path=str(outcomes_path), vector_store=store, vectors_path=str(vectors_path))

    engine = DecisionEngine(store_id="test", rules=[], log_path=str(tmp_path / "log.jsonl"), memory=mem)

    # Create an approved decision and insert into pending
    signal = DecisionSignal(source="metrics", signal_type="anomaly", data={})
    decision = Decision(
        decision_id="dec_test",
        decision_type=DecisionType.PRICING,
        rule_id="pricing_margin_protect",
        title="Test Decision",
        description="Testing vector indexing",
        recommended_action="Adjust price",
        priority=DecisionPriority.NORMAL,
        impact_score=0.1,
        risk_score=0.1,
        confidence_score=0.9,
        signal=signal,
    )
    decision.status = DecisionStatus.APPROVED
    decision.created_at = datetime.now(timezone.utc)

    engine.pending_decisions[decision.decision_id] = decision

    # Execute - should index vector and persist vector sidecar
    ok = engine.execute_decision(decision.decision_id)
    assert ok is True

    # Vector should be indexed in InMemoryVectorStore
    assert "dec_test" in store._vectors
    vec = store._vectors["dec_test"]
    assert isinstance(vec, list) and len(vec) == store.dim

    # Sidecar file should contain a record for the decision
    lines = vectors_path.read_text(encoding="utf-8").strip().splitlines()
    assert any("dec_test" in line for line in lines)  # Ensure "dec_test" is present in the lines
