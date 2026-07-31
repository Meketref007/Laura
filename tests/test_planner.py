from __future__ import annotations

from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.goal_management import GoalManager, PriorityEngine
from shopee_agent.planner import Planner, PlanTask
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


class TestPlanner:
    def test_execute_respects_dependencies(self):
        planner = Planner()
        tasks = [
            PlanTask(task_id="task_b", name="B", action="do_b", dependencies=["task_a"]),
            PlanTask(task_id="task_a", name="A", action="do_a"),
            PlanTask(task_id="task_c", name="C", action="do_c", dependencies=["task_b"]),
        ]

        seen: list[str] = []

        result = planner.execute(tasks, lambda task: seen.append(task.task_id) or task.action)

        assert result.status == "completed"
        assert seen == ["task_a", "task_b", "task_c"]
        assert result.ordered_task_ids == ["task_a", "task_b", "task_c"]

    def test_execute_rolls_back_failed_task(self):
        planner = Planner()
        tasks = [
            PlanTask(task_id="task_a", name="A", action="do_a"),
            PlanTask(task_id="task_b", name="B", action="do_b", dependencies=["task_a"], retries=1, rollback_action="undo_b"),
        ]

        calls: list[str] = []

        def runner(task: PlanTask):
            calls.append(task.task_id)
            if task.task_id == "task_b":
                raise RuntimeError("boom")
            return task.action

        def rollback_runner(task: PlanTask):
            calls.append(f"rollback:{task.task_id}")
            return f"rolled:{task.task_id}"

        result = planner.execute(tasks, runner, rollback_runner=rollback_runner)

        assert result.status == "failed"
        assert result.failed_task_id == "task_b"
        assert result.task_results[-1].rolled_back is True
        assert any(call.startswith("rollback:") for call in calls)

    def test_build_plan_from_goal_has_dag_dependencies(self):
        planner = Planner()
        goal = GoalStack().top_goal()

        tasks = planner.build_plan_from_goal(goal)

        assert len(tasks) == 3
        assert tasks[1].dependencies == [tasks[0].task_id]
        assert tasks[2].dependencies == [tasks[1].task_id]


class TestPlannerIntegration:
    def test_decision_integrator_includes_planner_execution(self, tmp_path, monkeypatch):
        goal_manager = GoalManager(path=str(tmp_path / "goals_state.jsonl"))
        goal_manager.register_goal(
            name="Grow margin",
            objective="grow_margin_to_20",
            target_metrics={"margin_pct": 20.0},
            budget=2000.0,
            duration_days=90,
            priority=1,
            tags=["margin"],
        )

        integrator = DecisionIntegrator(
            engine=DummyEngine(),
            store_id="test_store",
            metrics_dir=str(tmp_path),
            goal_stack=GoalStack(),
            goal_manager=goal_manager,
            priority_engine=PriorityEngine(),
            planner=Planner(),
        )

        monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
        monkeypatch.setattr(integrator, "build_economic_context", lambda: build_context(current_margin_pct=19.0, advertising_roas=2.7))

        result = integrator.process_cycle()

        assert result["planner"] is not None
        assert result["planner"]["status"] == "completed"
        assert integrator.last_planner_execution is not None
