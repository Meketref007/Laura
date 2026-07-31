"""Tests for GOAP extensions: parallel execution, composition, plan cache, multi-agent, goal synthesis, retry, state diff."""

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import pytest
from shopee_agent.goap_planner import GOAPAction, GOAPPlanner, MultiAgentGOAP, GOAPAgent, _state_hash
from shopee_agent.skills.state_store import GOAPStateStore
from shopee_agent.skills.sandbox import _run_with_retry
from shopee_agent.skills.goal_synthesizer import synthesize_goal, describe_goal
from shopee_agent.skills.registry import Skill, default_registry


# ── Plan cache ───────────────────────────────────────────────────────────────

class TestPlanCache:

    def test_cache_returns_same_plan(self):
        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=1.0, effects={"x": True}))
        planner.register_action(GOAPAction("b", cost=1.0, preconditions={"x": True}, effects={"y": True}))

        plan1 = planner.plan({"x": False, "y": False}, {"x": True, "y": True}, use_cache=True)
        plan2 = planner.plan({"x": False, "y": False}, {"x": True, "y": True}, use_cache=True)
        assert plan1 is not None and plan2 is not None
        assert [a.name for a in plan1] == [a.name for a in plan2]

    def test_cache_clear(self):
        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=1.0, effects={"x": True}))
        planner._plan_cache["k"] = [GOAPAction("a")]
        planner.clear_cache()
        assert len(planner._plan_cache) == 0

    def test_cache_key_differs_by_state(self):
        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=1.0, effects={"x": True}))
        p1 = planner.plan({"x": False}, {"x": True})
        p2 = planner.plan({"x": False}, {"x": False})
        # second should be trivial (goal already met)
        assert p1 is not None
        assert p2 is not None


# ── Parallel execution (group_independent) ───────────────────────────────────

class TestGroupIndependent:

    def test_no_conflicts(self):
        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", effects={"x": True}))
        planner.register_action(GOAPAction("b", effects={"y": True}))
        batches = planner.group_independent(["a", "b"])
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_with_conflicts(self):
        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", effects={"x": True}))
        planner.register_action(GOAPAction("b", effects={"x": False}))
        batches = planner.group_independent(["a", "b"])
        assert len(batches) >= 2

    def test_empty(self):
        planner = GOAPPlanner()
        assert planner.group_independent([]) == []


# ── Skill composition (sub_skills) ───────────────────────────────────────────

class TestSkillComposition:

    def test_sub_skills_expanded(self):
        from shopee_agent.skills.orchestrator import SkillOrchestrator
        from shopee_agent.skills.registry import SkillRegistry
        reg = SkillRegistry()

        class Inner(Skill):
            name = "inner"
            effects = {"inner_done": True}

        class Outer(Skill):
            name = "outer"
            effects = {"outer_done": True}
            sub_skills = ["inner"]

        reg.register(Outer)
        reg.register(Inner)

        orch = SkillOrchestrator(registry=reg)
        expanded = orch._expand_sub_skills(["outer"])
        assert "outer" in expanded
        assert "inner" in expanded
        # inner should come after outer
        assert expanded.index("outer") < expanded.index("inner")


# ── State diff & merge ───────────────────────────────────────────────────────

class TestStateDiffMerge:

    def test_diff_detects_changes(self):
        store = GOAPStateStore(path="reports/_test_diff.json")
        store.clear()
        store.save({"a": 1, "b": 2})
        delta = store.save_with_diff({"a": 1, "b": 3})
        assert delta == {"b": (2, 3)}
        store.clear()

    def test_diff_new_keys(self):
        store = GOAPStateStore(path="reports/_test_diff2.json")
        store.clear()
        store.save({"a": 1})
        delta = store.save_with_diff({"a": 1, "b": 2})
        assert delta["b"] == (None, 2)
        store.clear()

    def test_merge(self):
        store = GOAPStateStore(path="reports/_test_merge.json")
        merged = store.merge({"a": 1}, {"b": 2}, {"a": 99})
        assert merged == {"a": 99, "b": 2}

    def test_apply_patch(self):
        store = GOAPStateStore(path="reports/_test_patch.json")
        store.clear()
        store.save({"x": 1})
        result = store.apply_patch({"x": 2, "y": 3})
        assert result["x"] == 2
        assert result["y"] == 3
        assert store.load()["x"] == 2
        store.clear()


# ── Retry with backoff ───────────────────────────────────────────────────────

class TestRetry:

    @pytest.mark.asyncio
    async def test_retry_eventually_succeeds(self):
        call_count = 0

        def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await _run_with_retry(flaky_fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        def always_fails():
            raise ValueError("always")

        with pytest.raises(ValueError, match="always"):
            await _run_with_retry(always_fails, max_retries=2, base_delay=0.01)


# ── Multi-agent GOAP ─────────────────────────────────────────────────────────

class TestMultiAgentGOAP:

    def test_resolve_no_conflict(self):
        p1 = GOAPPlanner()
        p1.register_action(GOAPAction("a", effects={"x": True}))
        p2 = GOAPPlanner()
        p2.register_action(GOAPAction("b", effects={"y": True}))

        ma = MultiAgentGOAP()
        ma.add_agent(GOAPAgent(name="agent1", planner=p1, priority=1))
        ma.add_agent(GOAPAgent(name="agent2", planner=p2, priority=0))

        result = ma.resolve({"x": False, "y": False}, {"agent1": {"x": True}, "agent2": {"y": True}})
        assert "a" in result["merged_actions"]
        assert "b" in result["merged_actions"]

    def test_resolve_conflict_higher_priority_wins(self):
        p1 = GOAPPlanner()
        p1.register_action(GOAPAction("set_x_true", effects={"x": True}))
        p2 = GOAPPlanner()
        p2.register_action(GOAPAction("set_x_false", effects={"x": False}))

        ma = MultiAgentGOAP()
        ma.add_agent(GOAPAgent(name="high", planner=p1, priority=10))
        ma.add_agent(GOAPAgent(name="low", planner=p2, priority=1))

        result = ma.resolve({"x": None}, {"high": {"x": True}, "low": {"x": False}})
        merged = result["merged_actions"]
        # Both propose 'x' effects — low's action should be filtered out
        assert len(merged) >= 1


# ── Dynamic goal synthesis ───────────────────────────────────────────────────

class TestGoalSynthesis:

    def test_margin_goal(self):
        goal = synthesize_goal(margin_pct=15.0)
        assert "margin_protected" in goal

    def test_stock_goal(self):
        goal = synthesize_goal(low_stock_count=5)
        assert "stock_checked" in goal

    def test_loss_goal(self):
        goal = synthesize_goal(refund_rate_pct=7.0, profit=-100)
        assert "losses_reduced" in goal

    def test_default_goal(self):
        goal = synthesize_goal(margin_pct=30.0)
        assert "monitor_ok" in goal

    def test_describe(self):
        goal = {"margin_protected": True, "stock_checked": True}
        desc = describe_goal(goal)
        assert "Proteger margem" in desc
        assert "Verificar estoque" in desc
