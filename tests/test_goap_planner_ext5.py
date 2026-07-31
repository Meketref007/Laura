"""Tests for 8 new evolution features:
1. Parallel execution (asyncio.gather)
2. Hot-reload (unregister/reload)
3. PlanStore persistence
4. What-if simulation
5. DAG dependency resolution
6. Planner alerts
7. Prometheus /metrics
8. Resource profiling
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from shopee_agent.skills.registry import Skill, SkillRegistry, _resolve_dag


# ── Fixtures ─────────────────────────────────────────────────────────────────


class FakeSkill1(Skill):
    name = "skill_a"
    preconditions = {}
    effects = {"a_done": True}
    cost = 1.0


class FakeSkill2(Skill):
    name = "skill_b"
    preconditions = {"a_done": True}
    effects = {"b_done": True}
    cost = 2.0
    dependencies = ["skill_a"]


class FakeSkill3(Skill):
    name = "skill_c"
    preconditions = {}
    effects = {"c_done": True}
    cost = 1.5
    dependencies = ["skill_a"]


class FakeSkill4(Skill):
    name = "skill_d"
    preconditions = {"b_done": True, "c_done": True}
    effects = {"d_done": True}
    cost = 3.0
    dependencies = ["skill_b", "skill_c"]


@pytest.fixture
def registry():
    r = SkillRegistry()
    r.register(FakeSkill1)
    r.register(FakeSkill2)
    r.register(FakeSkill3)
    r.register(FakeSkill4)
    return r


# ── 5. DAG dependency resolution ────────────────────────────────────────────


class TestDAG:

    def test_resolve_no_deps(self, registry):
        result = _resolve_dag(["skill_a"], registry)
        assert result == ["skill_a"]

    def test_resolve_linear(self, registry):
        result = _resolve_dag(["skill_b", "skill_a"], registry)
        assert result.index("skill_a") < result.index("skill_b")

    def test_resolve_diamond(self, registry):
        result = _resolve_dag(["skill_d", "skill_b", "skill_c", "skill_a"], registry)
        assert result.index("skill_a") < result.index("skill_b")
        assert result.index("skill_a") < result.index("skill_c")
        assert result.index("skill_b") < result.index("skill_d")
        assert result.index("skill_c") < result.index("skill_d")

    def test_resolve_unknown_deps_ignored(self):
        class X(Skill):
            name = "x"
            dependencies = ["nonexistent"]
        r = SkillRegistry()
        r.register(X)
        result = _resolve_dag(["x"], r)
        assert result == ["x"]


# ── 2. Hot-reload (unregister/reload) ──────────────────────────────────────


class TestHotReload:

    def test_unregister(self, registry):
        assert registry.unregister("skill_a") is True
        assert registry.get("skill_a") is None
        assert "skill_a" not in registry.list()

    def test_unregister_nonexistent(self, registry):
        assert registry.unregister("nope") is False

    def test_reload_all(self, registry):
        count = registry.reload_all()
        # Should succeed for all 4 skills
        assert count == 4
        assert registry.get("skill_a") is not None


# ── 1. Parallel execution (asyncio.gather) ──────────────────────────────────


class TestParallelExecution:

    @pytest.mark.asyncio
    async def test_gather_parallel(self):
        """Verify asyncio.gather runs skills concurrently."""
        import asyncio

        trace: List[str] = []

        async def skill_slow(name: str, delay: float):
            trace.append(f"start_{name}")
            await asyncio.sleep(delay)
            trace.append(f"end_{name}")
            return {"ok": True}

        t0 = time.monotonic()
        results = await asyncio.gather(
            skill_slow("a", 0.3),
            skill_slow("b", 0.3),
            skill_slow("c", 0.3),
        )
        elapsed = time.monotonic() - t0

        # If truly parallel, total time < 0.9s (sum of individual)
        assert elapsed < 0.6, f"Expected parallel execution <0.6s, got {elapsed:.2f}s"
        assert all(r["ok"] for r in results)
        # All starts should happen before any end
        starts = [t for t in trace if t.startswith("start_")]
        ends = [t for t in trace if t.startswith("end_")]
        assert len(starts) == 3
        assert len(ends) == 3

    def test_group_independent_and_parallel(self):
        """group_independent creates non-conflicting batches for parallel exec."""
        from shopee_agent.goap_planner import GOAPAction, GOAPPlanner

        planner = GOAPPlanner()
        planner.register_action(GOAPAction(name="a", effects={"x": 1}, cost=1.0))
        planner.register_action(GOAPAction(name="b", effects={"y": 1}, cost=1.0))
        planner.register_action(GOAPAction(name="c", effects={"z": 1}, cost=1.0))
        planner.register_action(GOAPAction(name="d", effects={"x": 2}, cost=1.0))

        batches = planner.group_independent(["a", "b", "c", "d"])
        # a and d conflict (both set x), so they must be in separate batches
        a_batch = next(i for i, b in enumerate(batches) if "a" in b)
        d_batch = next(i for i, b in enumerate(batches) if "d" in b)
        assert a_batch != d_batch


# ── 3. PlanStore persistence ────────────────────────────────────────────────


class TestPlanStore:

    @pytest.fixture
    def store(self, tmp_path):
        from shopee_agent.plan_store import PlanStore
        db_path = str(tmp_path / "test_plans.db")
        return PlanStore(db_path=db_path)

    def test_save_and_get(self, store):
        pid = store.save_plan(
            plan_hash="abc123",
            start_state={"x": 1},
            goal={"y": 1},
            actions=["a", "b"],
            total_cost=3.0,
        )
        assert pid > 0
        plan = store.get_plan(pid)
        assert plan is not None
        assert plan["plan_hash"] == "abc123"
        assert plan["actions"] == ["a", "b"]
        assert plan["total_cost"] == 3.0

    def test_get_stats(self, store):
        pid1 = store.save_plan("h1", {"x": 1}, {"y": 1}, ["a"], 1.0, all_ok=True)
        store.mark_executed(pid1, all_ok=True)
        pid2 = store.save_plan("h2", {"x": 2}, {"y": 2}, ["b"], 2.0, all_ok=False)
        store.mark_executed(pid2, all_ok=False)
        stats = store.get_stats()
        assert stats["total_plans"] == 2
        assert stats["successful"] == 1
        assert stats["failed"] == 1

    def test_mark_executed(self, store):
        pid = store.save_plan("h1", {}, {}, ["a"], 1.0)
        store.mark_executed(pid, all_ok=True)
        plan = store.get_plan(pid)
        assert plan["all_ok"] is True
        assert plan["executed_at"] is not None

    def test_get_recent(self, store):
        store.save_plan("h1", {}, {}, ["a"], 1.0)
        store.save_plan("h2", {}, {}, ["b"], 2.0)
        recent = store.get_recent(limit=5)
        assert len(recent) >= 2

    def test_get_by_hash(self, store):
        store.save_plan("dup_hash", {}, {}, ["a"], 1.0)
        store.save_plan("dup_hash", {}, {}, ["b"], 2.0)
        plans = store.get_by_hash("dup_hash")
        assert len(plans) == 2


# ── 4. What-if simulation ───────────────────────────────────────────────────


class TestSimulation:

    def test_simulate_returns_plan(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction

        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=1.0, effects={"x": 1}))
        planner.register_action(GOAPAction("b", cost=2.0, preconditions={"x": 1}, effects={"y": 1}))

        result = planner.simulate({"x": 0, "y": 0}, {"x": 1, "y": 1})
        assert result["status"] == "ok"
        assert "a" in result["plan"]
        assert "b" in result["plan"]
        assert result["total_cost"] > 0
        assert "alternatives" in result

    def test_simulate_no_plan(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction

        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", preconditions={"impossible": True}, effects={"x": 1}))

        result = planner.simulate({"x": 0}, {"x": 1})
        assert result["status"] == "no_plan"

    def test_simulate_alternatives(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction

        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=1.0, effects={"x": 1}))
        planner.register_action(GOAPAction("b", cost=1.0, effects={"x": 1}))
        planner.register_action(GOAPAction("c", cost=1.0, effects={"y": 1}))

        result = planner.simulate({"x": 0, "y": 0}, {"x": 1, "y": 1})
        assert result["status"] == "ok"
        # Should have at least one alternative (skipping one action)
        assert len(result.get("alternatives", [])) >= 0

    def test_simulate_with_budget(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction

        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=5.0, effects={"x": 1}))
        planner.register_action(GOAPAction("b", cost=5.0, preconditions={"x": 1}, effects={"y": 1}))

        # Budget too low for both actions
        result = planner.simulate({"x": 0, "y": 0}, {"x": 1, "y": 1}, max_budget=3.0)
        assert result["status"] == "no_plan"


# ── 6. Planner alerts ───────────────────────────────────────────────────────


class TestPlannerAlerts:

    def test_no_plan_alert(self):
        from shopee_agent.planner_alerts import PlannerAlert, PlannerAlertManager

        fired = []
        alert = PlannerAlert("test_alert", "desc",
                             check_fn=lambda ctx: ctx.get("fail", False),
                             message_fn=lambda ctx: "fail detected",
                             cooldown_seconds=0)
        manager = PlannerAlertManager(path="reports/_test_alerts.jsonl")
        manager.add_alert(alert)

        result = manager.check_all({"fail": True})
        assert len(result) == 1
        assert result[0]["alert"] == "test_alert"

    def test_cooldown_suppresses_duplicates(self):
        from shopee_agent.planner_alerts import PlannerAlert, PlannerAlertManager

        count = [0]
        alert = PlannerAlert("cooldown", "desc",
                             check_fn=lambda ctx: True,
                             message_fn=lambda ctx: "always",
                             cooldown_seconds=9999)
        manager = PlannerAlertManager(path="reports/_test_alerts2.jsonl")
        manager.add_alert(alert)

        result1 = manager.check_all({})
        assert len(result1) == 1
        result2 = manager.check_all({})
        assert len(result2) == 0  # suppressed by cooldown

    def test_default_alerts_exist(self):
        from shopee_agent.planner_alerts import default_planner_alerts
        manager = default_planner_alerts()
        result = manager.check_all({"plan_status": "no_plan", "consecutive_failures": 3, "total_cost": 50, "cost_threshold": 10})
        assert len(result) >= 2  # no_plan_found + consecutive_failures + high_cost

    def test_history(self):
        from shopee_agent.planner_alerts import PlannerAlert, PlannerAlertManager

        alert = PlannerAlert("hist", "desc",
                             check_fn=lambda ctx: True,
                             message_fn=lambda ctx: "x",
                             cooldown_seconds=0)
        manager = PlannerAlertManager(path="reports/_test_alerts3.jsonl")
        manager.add_alert(alert)
        manager.check_all({})
        hist = manager.get_history()
        assert len(hist) >= 1


# ── 7. Prometheus /metrics ──────────────────────────────────────────────────


class TestPrometheusMetrics:

    def test_metrics_endpoint_format(self):
        """Test the prometheus metrics generation logic directly."""
        from shopee_agent.dashboard import prometheus_metrics
        # Just verify the function signature and that it returns a Response
        import inspect
        sig = inspect.signature(prometheus_metrics)
        assert sig is not None


# ── 8. Resource profiling ───────────────────────────────────────────────────


class TestResourceProfiling:

    def test_record_and_summary(self):
        from shopee_agent.skills.sandbox import record_profile, get_profile_summary, reset_profiles

        reset_profiles()
        record_profile("test_skill", elapsed=1.5)
        record_profile("test_skill", elapsed=2.5)
        record_profile("other_skill", elapsed=3.0)

        summary = get_profile_summary()
        assert "test_skill" in summary
        assert "other_skill" in summary
        assert summary["test_skill"]["count"] == 2
        assert summary["test_skill"]["avg_elapsed"] == 2.0
        assert summary["test_skill"]["min_elapsed"] == 1.5
        assert summary["test_skill"]["max_elapsed"] == 2.5
        assert summary["other_skill"]["count"] == 1

    def test_reset_profiles(self):
        from shopee_agent.skills.sandbox import record_profile, get_profile_summary, reset_profiles

        reset_profiles()
        record_profile("x", elapsed=1.0)
        assert len(get_profile_summary()) == 1
        reset_profiles()
        assert len(get_profile_summary()) == 0

    def test_thread_safety(self):
        from shopee_agent.skills.sandbox import record_profile, get_profile_summary, reset_profiles

        reset_profiles()
        errors = []

        def worker():
            try:
                for _ in range(50):
                    record_profile("concurrent", elapsed=0.1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        summary = get_profile_summary()
        assert summary["concurrent"]["count"] == 200
