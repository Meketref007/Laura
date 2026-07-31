from __future__ import annotations

import json

import shopee_agent.cli as cli
from shopee_agent.autonomous_strategy import AutonomousStrategyLayer
from shopee_agent.decision_engine import EconomicContext


def build_context(**overrides):
    base = dict(
        current_margin_pct=13.0,
        margin_target_pct=18.0,
        daily_revenue_usd=4200.0,
        cash_buffer_usd=45000.0,
        inventory_days_on_hand=10,
        stock_risk_level="normal",
        active_promotions=1,
        advertising_spend_daily_usd=700.0,
        advertising_roas=2.4,
        customer_satisfaction_score=86.0,
        recent_anomalies=["competitor_price_drop"],
    )
    base.update(overrides)
    return EconomicContext(**base)


def test_autonomous_strategy_layer_builds_actionable_snapshot(tmp_path):
    strategy = AutonomousStrategyLayer()
    snapshot = strategy.evaluate(build_context(), horizon_days=21)

    assert snapshot.status in {"needs_attention", "ready_for_growth", "at_risk"}
    assert snapshot.scenarios
    assert snapshot.recommendations
    assert snapshot.watchpoints
    assert snapshot.strategic_plan is not None
    assert snapshot.plan_timeline is not None
    assert snapshot.plan_assessment is not None
    assert any(signal.name in {"margin_gap", "competitive_price_drop", "branding_opportunity", "roas_pressure"} for signal in snapshot.signals)


def test_strategy_summary_cli_outputs_json(tmp_path, monkeypatch):
    output_path = tmp_path / "strategy_snapshot.json"

    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "strategy-summary",
        "--horizon-days",
        "21",
        "--output",
        str(output_path),
    ])

    exit_code = cli.main()

    assert exit_code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["horizon_days"] == 21
    assert payload["scenarios"]
    assert payload["recommendations"]