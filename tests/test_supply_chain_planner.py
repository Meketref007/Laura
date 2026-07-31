"""Tests for Phase 40 supply chain planning."""

from __future__ import annotations

import json

from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.predictive_analytics import PredictiveAnalytics
from shopee_agent.supply_chain_planner import SupplyChainPlanner


class DummyEngine:
    def process_signal(self, signal, context):
        return []


def write_inventory_snapshot(path):
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-14T00:00:00+00:00",
                "shop_id": 123,
                "items_seen": 3,
                "low_stock_threshold": 5,
                "low_stock_items": [
                    {"item_id": 1, "item_name": "SKU A", "stock": 2, "threshold": 5, "source": "detail"},
                    {"item_id": 2, "item_name": "SKU B", "stock": 4, "threshold": 5, "source": "detail"},
                ],
                "low_stock_count": 2,
                "sample_items": [],
                "inventory_ok": True,
            }
        ),
        encoding="utf-8",
    )


class TestSupplyChainPlanner:
    def test_plan_supply_chain_builds_procurement_actions(self, tmp_path):
        snapshot = tmp_path / "laura_inventory_monitor_latest.json"
        write_inventory_snapshot(snapshot)

        planner = SupplyChainPlanner(reports_dir=str(tmp_path))
        plan = planner.plan_supply_chain(horizon_days=14)

        assert plan.low_stock_count == 2
        assert len(plan.procurement_recommendations) == 2
        assert len(plan.logistics_recommendations) == 2
        assert plan.procurement_recommendations[0].preferred_supplier in {"local_fast_supplier", "regional_balanced_supplier", "low_cost_supplier"}
        assert plan.risks

    def test_supply_chain_plan_adapts_to_cash_and_inventory_pressure(self, tmp_path):
        snapshot = tmp_path / "laura_inventory_monitor_latest.json"
        write_inventory_snapshot(snapshot)

        planner = SupplyChainPlanner(reports_dir=str(tmp_path))
        plan = planner.plan_supply_chain(horizon_days=14)
        context = EconomicContext(
            current_margin_pct=16.0,
            margin_target_pct=18.0,
            daily_revenue_usd=4500.0,
            cash_buffer_usd=15000.0,
            inventory_days_on_hand=6,
            stock_risk_level="high",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=2.1,
            customer_satisfaction_score=80.0,
            recent_anomalies=[],
        )

        adapted = planner.adapt_supply_chain_plan(plan, context)
        assert any(rec.negotiation_hint.startswith("Prioritize payment terms") for rec in adapted.procurement_recommendations)
        assert all(log.priority == "high" for log in adapted.logistics_recommendations)


class TestSupplyChainIntegration:
    def test_decision_integrator_includes_supply_chain_plan(self, tmp_path, monkeypatch):
        snapshot = tmp_path / "laura_inventory_monitor_latest.json"
        write_inventory_snapshot(snapshot)

        analytics = PredictiveAnalytics(reports_dir=str(tmp_path))
        planner = SupplyChainPlanner(reports_dir=str(tmp_path), predictive_analytics=analytics)
        engine = DummyEngine()
        integrator = DecisionIntegrator(
            engine=engine,
            store_id="test_store",
            metrics_dir=str(tmp_path),
            predictive_analytics=analytics,
            supply_chain_planner=planner,
        )

        monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
        monkeypatch.setattr(
            integrator,
            "build_economic_context",
            lambda: EconomicContext(
                current_margin_pct=16.0,
                margin_target_pct=18.0,
                daily_revenue_usd=4500.0,
                cash_buffer_usd=50000.0,
                inventory_days_on_hand=6,
                stock_risk_level="high",
                active_promotions=0,
                advertising_spend_daily_usd=500.0,
                advertising_roas=2.1,
                customer_satisfaction_score=80.0,
                recent_anomalies=[],
            ),
        )

        result = integrator.process_cycle()

        assert result["supply_chain"] is not None
        assert result["supply_chain"]["procurement_recommendations"]
        assert integrator.last_supply_chain_plan is not None
