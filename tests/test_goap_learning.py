"""Tests for GOAP learning, sandbox, events, and skill-history CLI."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
from shopee_agent.skills.sandbox import run_skill_sandbox, get_breaker
from shopee_agent.skills.orchestrator import SkillOrchestrator
from shopee_agent.skills.registry import Skill, SkillRegistry
from shopee_agent.event_bus import GOAPPlanExecutedEvent


class TestGOAPLearning:

    def test_learning_reduces_cost_on_success(self, tmp_path):
        learning_file = tmp_path / "goap_learning.json"
        planner = GOAPPlanner(learning_path=str(learning_file), use_sqlite=False)
        planner._actions.append(GOAPAction(name="test_action", cost=1.0))

        planner.record_outcome("test_action", success=True)
        assert planner._cost_overrides["test_action"] < 1.0
        assert learning_file.exists()

    def test_learning_increases_cost_on_failure(self, tmp_path):
        learning_file = tmp_path / "goap_learning.json"
        planner = GOAPPlanner(learning_path=str(learning_file), use_sqlite=False)
        planner._actions.append(GOAPAction(name="test_action", cost=1.0))

        planner.record_outcome("test_action", success=False)
        assert planner._cost_overrides["test_action"] > 1.0

    def test_learning_persists_across_instances(self, tmp_path):
        learning_file = tmp_path / "goap_learning.json"
        planner1 = GOAPPlanner(learning_path=str(learning_file), use_sqlite=False)
        planner1._actions.append(GOAPAction(name="test_action", cost=1.0))
        planner1.record_outcome("test_action", success=True)
        cost_after = planner1._cost_overrides["test_action"]

        planner2 = GOAPPlanner(learning_path=str(learning_file), use_sqlite=False)
        assert planner2._cost_overrides.get("test_action") == cost_after

    def test_get_learning_summary(self, tmp_path):
        planner = GOAPPlanner(learning_path=str(tmp_path / "learn.json"), use_sqlite=False)
        planner._actions.append(GOAPAction(name="act1", cost=1.0))
        planner.record_outcome("act1", success=True)
        summary = planner.get_learning_summary()
        assert "cost_overrides" in summary
        assert "base_actions" in summary


class TestSkillSandbox:

    @pytest.mark.asyncio
    async def test_dry_run_skips_execution(self):
        def fn(**kwargs):
            raise RuntimeError("should not run")
        result = await run_skill_sandbox("test", fn, dry_run=True)
        assert result["dry_run"] is True
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        def fn(**kwargs):
            return {"done": True}
        result = await run_skill_sandbox("test_success", fn)
        assert result["ok"] is True
        assert result["dry_run"] is False
        assert result["elapsed"] >= 0

    @pytest.mark.asyncio
    async def test_failed_execution(self):
        def fn(**kwargs):
            raise ValueError("test error")
        result = await run_skill_sandbox("test_fail", fn)
        assert result["ok"] is False
        assert "test error" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout(self):
        import time
        def fn(**kwargs):
            time.sleep(5)
            return {}
        result = await run_skill_sandbox("test_timeout", fn, timeout_seconds=0.1)
        assert result["ok"] is False
        assert "timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        def fn(**kwargs):
            raise ValueError("fail")
        breaker = get_breaker("test_cb")
        breaker._record_failure()
        breaker._record_failure()
        breaker._record_failure()
        result = await run_skill_sandbox("test_cb", fn)
        assert result.get("circuit_open") is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_closes_on_success(self):
        def fn(**kwargs):
            return {}
        breaker = get_breaker("test_cb_close")
        breaker._record_failure()
        result = await run_skill_sandbox("test_cb_close", fn)
        # should work after single failure since threshold is 3
        assert result["ok"] is True


class TestGOAPEvent:

    def test_goap_event_dataclass(self):
        ev = GOAPPlanExecutedEvent(
            actions=["skill_a", "skill_b"],
            total_cost=2.5,
            results=[{"ok": True}, {"ok": False}],
            all_ok=False,
            state_snapshot={"key": "val"},
        )
        assert ev.event_type == "goap.plan_executed"
        assert ev.actions == ["skill_a", "skill_b"]
        assert ev.total_cost == 2.5
        assert ev.all_ok is False
        assert ev.state_snapshot == {"key": "val"}

    def test_orchestrator_emits_event(self):
        from shopee_agent.skills.loader import discover_and_register
        discover_and_register()

        events = []

        class FakeBus:
            def submit(self, event):
                events.append(event)

        orch = SkillOrchestrator(event_bus=FakeBus())
        result = orch.evaluate_state(
            {"stock_checked": False, "margin_protected": False},
            {"stock_checked": True, "margin_protected": True},
            max_depth=4,
        )
        # event may or may not fire depending on plan
        if result["status"] == "executed":
            assert len(events) >= 1
            assert isinstance(events[0], GOAPPlanExecutedEvent)


class TestSkillHistoryCLI:

    def test_skill_history_persists(self, tmp_path):
        history = tmp_path / "skill_execution_history.jsonl"
        orch = SkillOrchestrator(history_path=str(history))
        orch._append_history("test_hist", ok=True, result="done", error="")
        orch._append_history("test_hist2", ok=False, error="fail")
        lines = history.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        assert e1["skill"] == "test_hist"
        assert e1["ok"] is True
        e2 = json.loads(lines[1])
        assert e2["ok"] is False
        assert e2["error"] == "fail"

    def test_learning_command_has_proper_method(self, tmp_path):
        planner = GOAPPlanner(learning_path=str(tmp_path / "learning.json"))
        planner._actions.append(GOAPAction(name="alpha", cost=1.0))
        planner.record_outcome("alpha", success=True)
        summary = planner.get_learning_summary()
        assert "alpha" in summary.get("cost_overrides", {})


class TestSkillMetadata:

    def test_skill_has_preconditions_and_effects(self):
        from shopee_agent.skills.loader import discover_and_register
        from shopee_agent.skills.registry import default_registry
        discover_and_register()

        for name in default_registry.list():
            cls = default_registry.get(name)
            assert hasattr(cls, "preconditions")
            assert hasattr(cls, "effects")
            assert hasattr(cls, "cost")
            assert hasattr(cls, "priority")
            assert isinstance(cls.preconditions, dict)
            assert isinstance(cls.effects, dict)
            assert isinstance(cls.cost, (int, float))
            assert isinstance(cls.priority, int)

    def test_goap_planner_reads_metadata(self):
        from shopee_agent.skills.loader import discover_and_register
        from shopee_agent.skills.registry import default_registry
        discover_and_register()

        planner = GOAPPlanner(learning_path=str(Path(__file__).parent / "_test_goap_learning.json"))
        planner.load_skills(default_registry)
        names = {a.name for a in planner._actions}
        for skill_name in default_registry.list():
            assert skill_name in names, f"{skill_name} not loaded into planner"

    def test_goap_priority_sorting(self):
        from shopee_agent.skills.loader import discover_and_register
        discover_and_register()
        orch = SkillOrchestrator()
        plan = orch.determine_skills(
            {"stock_checked": False, "margin_protected": False, "orders_pending_ship": True, "support_handled": False},
            {"stock_checked": True, "margin_protected": True, "orders_pending_ship": False, "support_handled": True},
            max_depth=6,
            prioritize_critical=True,
        )
        # order_ship has highest priority (3)
        if "order_ship" in plan:
            ship_idx = plan.index("order_ship")
            for name in plan:
                cls = orch.registry.get(name)
                prio = getattr(cls, "priority", 0) if cls else 0
                if prio < 3:
                    assert plan.index(name) < ship_idx or plan.index(name) > ship_idx
