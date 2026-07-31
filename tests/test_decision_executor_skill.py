from datetime import datetime, timezone
from shopee_agent.decision_integration import DecisionExecutor
from shopee_agent.decision_engine import Decision, DecisionPriority, DecisionType, DecisionSignal


def make_decision_with_skill(skill_name: str) -> Decision:
    sig = DecisionSignal(source="test", signal_type="manual", data={})
    dec = Decision(
        decision_id="skill1",
        decision_type=DecisionType.ALERTS,
        rule_id="r1",
        title="Run skill",
        description="Invoke a skill",
        recommended_action="run skill",
        priority=DecisionPriority.LOW,
        impact_score=0.0,
        risk_score=0.0,
        confidence_score=1.0,
        signal=sig,
    )
    dec.metadata["skill"] = skill_name
    # provide a default arg for simple echo skills
    dec.metadata["skill_args"] = ["ping"]
    dec.status = dec.status
    dec.created_at = datetime.now(timezone.utc)
    return dec


def test_executor_runs_skill():
    dec = make_decision_with_skill("EchoSkill")
    executor = DecisionExecutor(store_id="tstore", engine=None)
    ok = executor.execute(dec)
    assert ok is True
