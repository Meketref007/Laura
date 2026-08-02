from __future__ import annotations

from pathlib import Path

import pytest

from shopee_agent.ceo_mode import ceo_mode_enabled
from shopee_agent.decision_engine import (
    Decision,
    DecisionEngine,
    DecisionPriority,
    DecisionSignal,
    DecisionStatus,
    DecisionType,
)
from shopee_agent.decision_integration import DecisionIntegrator


def test_ceo_mode_enabled_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAURA_CEO_MODE", raising=False)
    assert ceo_mode_enabled() is False
    for value in ("1", "true", "yes", "on", "TRUE", "Sim"):
        monkeypatch.setenv("LAURA_CEO_MODE", value)
        assert ceo_mode_enabled() is True, f"LAURA_CEO_MODE={value} deveria ativar"
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("LAURA_CEO_MODE", value)
        assert ceo_mode_enabled() is False, f"LAURA_CEO_MODE={value} deveria desativar"


def _make_pending_high_decision(decision_id: str) -> Decision:
    sig = DecisionSignal(source="test", signal_type="manual", data={})
    return Decision(
        decision_id=decision_id,
        decision_type=DecisionType.ALERTS,
        rule_id="r_test",
        title="Test High",
        description="test",
        recommended_action="echo",
        priority=DecisionPriority.HIGH,
        impact_score=0.0,
        risk_score=0.0,
        confidence_score=0.9,
        signal=sig,
    )


def _run_cycle_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ceo_mode: bool, decision: Decision) -> tuple[list[str], Decision]:
    engine = DecisionEngine(store_id="tstore", rules=[])
    engine.pending_decisions[decision.decision_id] = decision
    integrator = DecisionIntegrator(engine=engine, store_id="tstore", metrics_dir=str(tmp_path / "reports"))

    from shopee_agent.autonomous_loop import AutonomousLoop

    monkeypatch.setenv("LAURA_CEO_MODE", "1" if ceo_mode else "0")
    loop = AutonomousLoop(client=None, access_token=None, shop_id=None, reports_dir=tmp_path / "reports")
    loop.external_engine = engine
    loop.external_integrator = integrator
    monkeypatch.setattr(loop, "_send_telegram", lambda _text: True)

    executed: list[str] = []
    monkeypatch.setattr(
        "shopee_agent.autonomous_loop.DecisionExecutor.execute",
        lambda self, d: executed.append(d.decision_id) or True,
    )
    result = loop.run_cycle()
    assert "executed" in result
    return executed, decision


def test_ceo_mode_auto_approves_and_executes_high_decision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = _make_pending_high_decision("d_high_ceo")
    executed, decision = _run_cycle_with(monkeypatch, tmp_path, ceo_mode=True, decision=decision)
    assert decision.status != DecisionStatus.PENDING
    assert decision.decision_id in executed


def test_ceo_mode_skips_risky_decision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = _make_pending_high_decision("d_high_risky")
    decision.risk_score = 0.9
    decision.confidence_score = 0.8
    executed, decision = _run_cycle_with(monkeypatch, tmp_path, ceo_mode=True, decision=decision)
    assert decision.status == DecisionStatus.PENDING
    assert decision.decision_id not in executed


def test_ceo_mode_skips_low_confidence_decision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = _make_pending_high_decision("d_high_lowconf")
    decision.risk_score = 0.1
    decision.confidence_score = 0.4
    executed, decision = _run_cycle_with(monkeypatch, tmp_path, ceo_mode=True, decision=decision)
    assert decision.status == DecisionStatus.PENDING
    assert decision.decision_id not in executed


def test_ceo_mode_off_does_not_execute_pending_high_decision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = _make_pending_high_decision("d_high_no_ceo")
    executed, decision = _run_cycle_with(monkeypatch, tmp_path, ceo_mode=False, decision=decision)
    assert decision.status == DecisionStatus.PENDING
    assert decision.decision_id not in executed


def test_chat_auto_human_approval_defaults_from_ceo_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from shopee_agent.chat_auto import ChatAutomation

    monkeypatch.setenv("LAURA_CEO_MODE", "1")
    auto_ceo = ChatAutomation(client=None, use_ollama=False, reports_dir=tmp_path / "reports")
    assert auto_ceo.human_approval is False

    monkeypatch.setenv("LAURA_CEO_MODE", "0")
    auto_manual = ChatAutomation(client=None, use_ollama=False, reports_dir=tmp_path / "reports")
    assert auto_manual.human_approval is True

    auto_explicit = ChatAutomation(
        client=None, use_ollama=False, reports_dir=tmp_path / "reports", human_approval=True
    )
    assert auto_explicit.human_approval is True


def test_ceo_mode_disables_seller_center_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from shopee_agent.seller_center_actions import SellerCenterActions

    actions = SellerCenterActions(client=object())

    monkeypatch.setenv("SELLER_CENTER_DRY_RUN", "1")
    monkeypatch.setenv("LAURA_CEO_MODE", "1")
    assert actions._is_dry_run() is False

    monkeypatch.setenv("LAURA_CEO_MODE", "0")
    assert actions._is_dry_run() is True

    monkeypatch.setenv("SELLER_CENTER_DRY_RUN", "0")
    assert actions._is_dry_run() is False


def test_guardrails_tightened_risk_and_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from shopee_agent.decision_engine import DecisionEngine

    engine = DecisionEngine(store_id="tstore", rules=[])
    ctx = engine.build_economic_context() if hasattr(engine, "build_economic_context") else None
    if ctx is None:
        from shopee_agent.decision_engine import EconomicContext

        ctx = EconomicContext(
            current_margin_pct=20.0,
            margin_target_pct=18.0,
            daily_revenue_usd=5000.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=15,
            stock_risk_level="normal",
            active_promotions=2,
            advertising_spend_daily_usd=500.0,
            advertising_roas=2.5,
            customer_satisfaction_score=85.0,
            recent_anomalies=[],
        )
    decision = _make_pending_high_decision("d_guardrail_risk")
    decision.risk_score = 0.7
    decision.confidence_score = 0.9
    guards = engine._evaluate_guardrails(decision, ctx)
    assert guards["acceptable_risk"] is False

    decision2 = _make_pending_high_decision("d_guardrail_conf")
    decision2.risk_score = 0.2
    decision2.confidence_score = 0.5
    guards2 = engine._evaluate_guardrails(decision2, ctx)
    assert guards2["reasonable_confidence"] is False
