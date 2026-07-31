import os
from shopee_agent.decision_integration import DecisionExecutor
from shopee_agent.decision_engine import Decision, DecisionPriority, DecisionType, DecisionSignal, DecisionStatus


def test_skill_audit_log(tmp_path):
    # Ensure reports dir is isolated for test
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    # patch working dir reports path by changing CWD for this test
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        sig = DecisionSignal(source="test", signal_type="manual", data={})
        dec = Decision(
            decision_id="audit_test",
            decision_type=DecisionType.ALERTS,
            rule_id="r_audit",
            title="Audit skill",
            description="Test audit",
            recommended_action="run",
            priority=DecisionPriority.LOW,
            impact_score=0.0,
            risk_score=0.0,
            confidence_score=1.0,
            signal=sig,
        )
        dec.metadata["skill"] = "EchoSkill"
        dec.metadata["skill_args"] = ["ping"]
        dec.status = DecisionStatus.APPROVED

        executor = DecisionExecutor(store_id="tstore", engine=None)
        ok = executor.execute(dec)
        assert ok

        p = reports_dir / "laura_skill_executions.jsonl"
        assert p.exists()
        with p.open("r", encoding="utf-8") as fh:
            lines = [l.strip() for l in fh.readlines() if l.strip()]
        assert any("audit_test" in l for l in lines)

    finally:
        os.chdir(orig_cwd)
