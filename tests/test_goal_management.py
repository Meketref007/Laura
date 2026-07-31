from __future__ import annotations

from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.goal_management import GoalManager, PriorityEngine
from shopee_agent.strategic_planner import GoalStack


class DummyEngine:
    def process_signal(self, signal, context):
        return []


def build_context(**overrides):
    base = dict(
        current_margin_pct=11.0,
        margin_target_pct=18.0,
        daily_revenue_usd=4200.0,
        cash_buffer_usd=25000.0,
        inventory_days_on_hand=7,
        stock_risk_level="normal",
        active_promotions=1,
        advertising_spend_daily_usd=500.0,
        advertising_roas=1.4,
        customer_satisfaction_score=80.0,
        recent_anomalies=["margin_drop"],
    )
    base.update(overrides)
    return EconomicContext(**base)


class TestGoalManagement:
    def test_priority_engine_ranks_more_urgent_goals_first(self, tmp_path):
        manager = GoalManager(path=str(tmp_path / "goals_state.jsonl"))
        manager.register_goal(
            name="Improve ROAS",
            objective="achieve_roas_2_5x",
            target_metrics={"roas": 2.5},
            budget=1500.0,
            duration_days=30,
            priority=1,
            tags=["ads"],
        )
        manager.register_goal(
            name="Grow margin",
            objective="grow_margin_to_20",
            target_metrics={"margin_pct": 20.0},
            budget=2500.0,
            duration_days=90,
            priority=3,
            tags=["margin"],
        )

        ranked = manager.rank_goals(context=build_context())

        assert ranked[0]["goal"]["name"] == "Improve ROAS"
        assert ranked[0]["score"] >= ranked[1]["score"]

    def test_snapshot_includes_top_goal_and_rankings(self, tmp_path):
        manager = GoalManager(path=str(tmp_path / "goals_state_snapshot.jsonl"))
        manager.register_goal(
            name="Grow margin",
            objective="grow_margin_to_20",
            target_metrics={"margin_pct": 20.0},
            budget=2000.0,
            duration_days=90,
            priority=1,
            tags=["margin"],
        )

        snapshot = manager.snapshot(context=build_context(current_margin_pct=12.0))

        assert snapshot["total_goals"] == 1
        assert snapshot["top_goal"]["name"] == "Grow margin"
        assert snapshot["ranked_goals"]

    def test_decision_integrator_includes_goal_management(self, tmp_path, monkeypatch):
        goal_manager = GoalManager(path=str(tmp_path / "goals_state.jsonl"))
        goal_manager.register_goal(
            name="Improve ROAS",
            objective="achieve_roas_2_5x",
            target_metrics={"roas": 2.5},
            budget=1500.0,
            duration_days=30,
            priority=1,
            tags=["ads"],
        )

        integrator = DecisionIntegrator(
            engine=DummyEngine(),
            store_id="test_store",
            metrics_dir=str(tmp_path),
            strategic_planner=None,
            goal_stack=GoalStack(),
            goal_manager=goal_manager,
            priority_engine=PriorityEngine(),
        )

        monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
        monkeypatch.setattr(integrator, "build_economic_context", lambda: build_context(current_margin_pct=19.0, advertising_roas=2.7))

        result = integrator.process_cycle()

        assert result["goal_management"] is not None
        assert result["goal_management"]["top_goal"]["name"] == "Improve ROAS"
        assert integrator.last_goal_snapshot is not None
