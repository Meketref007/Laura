from unittest.mock import MagicMock
from shopee_agent.decision_engine import (
    Decision,
    DecisionType,
    DecisionPriority,
    DecisionStatus,
    DecisionSignal,
    DecisionEngine,
)
from shopee_agent.decision_memory import MemoryLayer
from shopee_agent.vector_store import InMemoryVectorStore
from shopee_agent.decision_integration import DecisionExecutor


def test_executor_notifies_engine_and_memory():
    store = InMemoryVectorStore()
    mem = MemoryLayer(path="reports/test_exec_outcomes.jsonl", vector_store=store)

    engine = DecisionEngine(store_id="tstore", rules=[], memory=mem)

    sig = DecisionSignal(source="metrics.test", signal_type="anomaly", data={})

    decision = Decision(
        decision_id="td1",
        decision_type=DecisionType.ALERTS,
        rule_id="r_test",
        title="Test Decision",
        description="",
        recommended_action="do something",
        priority=DecisionPriority.NORMAL,
        impact_score=0.1,
        risk_score=0.1,
        confidence_score=0.9,
        signal=sig,
    )

    # Place into pending and mark approved
    decision.status = DecisionStatus.APPROVED
    engine.pending_decisions[decision.decision_id] = decision

    executor = DecisionExecutor(store_id="tstore", engine=engine, client=MagicMock())

    ok = executor.execute(decision)
    assert ok is True

    # Engine should have marked it executed
    assert engine.pending_decisions[decision.decision_id].status == DecisionStatus.EXECUTED

    # Memory should contain an outcome for the decision
    outcomes = mem.list_outcomes(limit=50)
    ids = [o.decision_id for o in outcomes]
    assert "td1" in ids

    # Vector should be indexed in the in-memory store
    assert "td1" in store._vectors
