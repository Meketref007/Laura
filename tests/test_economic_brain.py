from __future__ import annotations

import json


from shopee_agent import cli
from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.economic_brain import EconomicBrain


class DummyEngine:
    def process_signal(self, signal, context):
        return []


def _write_history(tmp_path):
    history = tmp_path / "reports" / "laura_profitability_history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-05-10T00:00:00+00:00",
            "metrics": {"revenue": 1000.0, "cogs": 600.0, "ad_spend": 120.0, "shipping_subsidy": 30.0, "refunds": 20.0, "orders": 12, "profit": 230.0, "margin_pct": 23.0, "roas": 8.33, "refund_rate_pct": 2.0},
        },
        {
            "timestamp": "2026-05-11T00:00:00+00:00",
            "metrics": {"revenue": 3000.0, "cogs": 1900.0, "ad_spend": 340.0, "shipping_subsidy": 100.0, "refunds": 60.0, "orders": 30, "profit": 600.0, "margin_pct": 20.0, "roas": 8.82, "refund_rate_pct": 2.0},
        },
    ]
    history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    latest = tmp_path / "reports" / "laura_profitability_latest.json"
    latest.write_text(json.dumps(rows[-1]["metrics"]), encoding="utf-8")


def test_economic_brain_analyzes_forecast_and_scenarios(tmp_path):
    _write_history(tmp_path)
    brain = EconomicBrain(latest_path=str(tmp_path / "reports" / "laura_profitability_latest.json"), history_path=str(tmp_path / "reports" / "laura_profitability_history.jsonl"))

    snapshot = brain.analyze()

    assert snapshot.current.revenue == 3000.0
    assert snapshot.history_points == 2
    assert snapshot.forecasts
    assert any(scenario.name == "growth_push" for scenario in snapshot.scenarios)
    assert snapshot.recommendations


def test_decision_integrator_includes_economic_brain_snapshot(tmp_path, monkeypatch):
    _write_history(tmp_path)
    brain = EconomicBrain(latest_path=str(tmp_path / "reports" / "laura_profitability_latest.json"), history_path=str(tmp_path / "reports" / "laura_profitability_history.jsonl"))
    integrator = DecisionIntegrator(
        engine=DummyEngine(),
        store_id="test_store",
        metrics_dir=str(tmp_path / "reports"),
        economic_brain=brain,
    )

    monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
    monkeypatch.setattr(integrator, "build_economic_context", lambda: EconomicContext(
        current_margin_pct=20.0,
        margin_target_pct=18.0,
        daily_revenue_usd=3000.0,
        cash_buffer_usd=25000.0,
        inventory_days_on_hand=7,
        stock_risk_level="normal",
        active_promotions=1,
        advertising_spend_daily_usd=340.0,
        advertising_roas=8.82,
        customer_satisfaction_score=80.0,
        recent_anomalies=[],
    ))

    result = integrator.process_cycle()

    assert result["economic_brain"] is not None
    assert result["economic_brain"]["current"]["revenue"] == 3000.0
    assert integrator.last_economic_brain_snapshot is not None


def test_build_parser_includes_economic_brain_command():
    parser = cli.build_parser()
    args = parser.parse_args([
        "economic-brain-summary",
        "--latest-file",
        "reports/laura_profitability_latest.json",
        "--history-file",
        "reports/laura_profitability_history.jsonl",
    ])

    assert args.command == "economic-brain-summary"
    assert args.latest_file == "reports/laura_profitability_latest.json"
    assert args.history_file == "reports/laura_profitability_history.jsonl"


def test_main_dispatches_economic_brain_summary_without_loading_shopee_config(tmp_path, monkeypatch):
    _write_history(tmp_path)
    monkeypatch.setattr(cli, "initialize_default_circuit_breakers", lambda: None)
    monkeypatch.setattr(cli.sys, "argv", [
        "laura",
        "economic-brain-summary",
        "--latest-file",
        str(tmp_path / "reports" / "laura_profitability_latest.json"),
        "--history-file",
        str(tmp_path / "reports" / "laura_profitability_history.jsonl"),
    ])

    exit_code = cli.main()

    assert exit_code == 0
