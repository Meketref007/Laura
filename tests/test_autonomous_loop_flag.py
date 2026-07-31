from pathlib import Path
from shopee_agent.autonomous_loop import AutonomousLoop
from shopee_agent.decision_engine import Decision, DecisionPriority, DecisionType, DecisionSignal, DecisionStatus
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.decision_engine import DecisionEngine


def test_auto_skills_flag_off():
    engine = DecisionEngine(store_id="tstore", rules=[])
    sig = DecisionSignal(source="test", signal_type="manual", data={})
    decision = Decision(
        decision_id="d_skill_flag",
        decision_type=DecisionType.ALERTS,
        rule_id="r_skill",
        title="Run Echo",
        description="Run example EchoSkill",
        recommended_action="echo",
        priority=DecisionPriority.LOW,
        impact_score=0.0,
        risk_score=0.0,
        confidence_score=1.0,
        signal=sig,
    )
    decision.status = DecisionStatus.APPROVED
    decision.metadata["skill"] = "EchoSkill"
    decision.metadata["skill_args"] = ["hello"]
    engine.pending_decisions[decision.decision_id] = decision

    integrator = DecisionIntegrator(engine=engine, store_id="tstore", metrics_dir=str(Path("reports")))
    loop = AutonomousLoop(client=None, access_token=None, shop_id=None, reports_dir=Path("reports"), external_engine=engine, external_integrator=integrator, enable_auto_skills=False)

    res = loop.run_cycle()
    assert decision.decision_id not in res.get("executed", [])
