"""Tests for Phase 38 strategic planning."""

from __future__ import annotations

from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.strategic_planner import Goal, GoalStack, PlanStatus, StrategicPlanner


class DummyEngine:
    def process_signal(self, signal, context):
        return []


def build_context(**overrides):
    base = dict(
        current_margin_pct=12.0,
        margin_target_pct=18.0,
        daily_revenue_usd=3200.0,
        cash_buffer_usd=50000.0,
        inventory_days_on_hand=6,
        stock_risk_level="high",
        active_promotions=0,
        advertising_spend_daily_usd=500.0,
        advertising_roas=1.3,
        customer_satisfaction_score=82.0,
        recent_anomalies=["margin_drop"],
    )
    base.update(overrides)
    return EconomicContext(**base)


class TestStrategicPlanner:
    def test_decompose_margin_goal(self):
        planner = StrategicPlanner()
        goal = Goal(
            name="Grow margin",
            objective="grow_margin_to_20",
            target_metrics={"margin_pct": 20.0},
            budget=2000.0,
            duration_days=90,
            priority=1,
        )

        plan = planner.decompose_goal(goal, context=build_context())

        assert len(plan.phases) == 3
        assert plan.phases[0].actions[0] == "protect margin first"
        assert plan.phases[1].dependencies == [plan.phases[0].phase_id]
        assert plan.success_criteria
        assert plan.rollback_condition

    def test_schedule_phases_respects_dependencies(self):
        planner = StrategicPlanner()
        goal = Goal(
            name="Launch product line",
            objective="launch_new_product_lines",
            target_metrics={"new_lines": 3.0},
            budget=5000.0,
            duration_days=60,
            priority=2,
        )

        plan = planner.decompose_goal(goal, context=build_context())
        timeline = planner.schedule_phases(plan)

        assert len(timeline.entries) == 3
        assert timeline.entries[0].start_day == 0
        assert timeline.entries[1].start_day >= timeline.entries[0].end_day
        assert timeline.total_duration_days > 0

    def test_monitor_and_adapt_plan(self):
        planner = StrategicPlanner()
        goal = Goal(
            name="Improve ROAS",
            objective="achieve_roas_2_5x",
            target_metrics={"roas": 2.5},
            budget=1500.0,
            duration_days=45,
            priority=2,
        )

        context = build_context(advertising_roas=1.2, current_margin_pct=11.0)
        plan = planner.decompose_goal(goal, context=context)
        assessment = planner.monitor_plan(plan, context)
        adapted = planner.adapt_plan(plan, context)

        assert assessment.status == PlanStatus.AT_RISK
        assert adapted.status == PlanStatus.AT_RISK
        assert adapted.phases[0].actions

    def test_goal_stack_top_goal(self):
        goal_stack = GoalStack()
        top_goal = goal_stack.top_goal()

        assert top_goal is not None
        assert top_goal.name == "Grow margin"


class TestStrategicPlannerIntegration:
    def test_decision_integrator_includes_strategic_plan(self, tmp_path, monkeypatch):
        engine = DummyEngine()
        planner = StrategicPlanner()
        integrator = DecisionIntegrator(
            engine=engine,
            store_id="test_store",
            metrics_dir=str(tmp_path),
            strategic_planner=planner,
            goal_stack=GoalStack(),
        )

        monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
        monkeypatch.setattr(integrator, "build_economic_context", lambda: build_context(current_margin_pct=21.0, advertising_roas=2.6))

        result = integrator.process_cycle()

        assert result["strategic_plan"] is not None
        assert result["strategic_plan"]["plan"] is not None
        assert result["strategic_plan"]["timeline"] is not None
        assert result["strategic_plan"]["assessment"] is not None
        assert integrator.last_strategic_plan is not None
