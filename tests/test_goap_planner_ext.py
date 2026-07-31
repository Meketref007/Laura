"""Tests for GOAP extensions: operator preconditions, reverse/compensation, state store, rate limiter, external discovery."""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from shopee_agent.goap_planner import GOAPAction, GOAPPlanner
from shopee_agent.skills.state_store import GOAPStateStore
from shopee_agent.skills.sandbox import RateLimiter, run_skill_sandbox, get_rate_limiter
from shopee_agent.skills.registry import default_registry, Skill


# ── Operator-based preconditions ──────────────────────────────────────────────

class TestGOAPActionOperators:

    def test_gt_precondition(self):
        a = GOAPAction(name="gt_test", preconditions={"gt_stock": 5}, effects={"checked": True})
        assert a.is_valid({"stock": 10})
        assert not a.is_valid({"stock": 5})
        assert not a.is_valid({"stock": 3})

    def test_gte_precondition(self):
        a = GOAPAction(name="gte_test", preconditions={"gte_stock": 5}, effects={"checked": True})
        assert a.is_valid({"stock": 5})
        assert a.is_valid({"stock": 10})
        assert not a.is_valid({"stock": 4})

    def test_lt_precondition(self):
        a = GOAPAction(name="lt_test", preconditions={"lt_stock": 5}, effects={"checked": True})
        assert a.is_valid({"stock": 3})
        assert not a.is_valid({"stock": 5})
        assert not a.is_valid({"stock": 10})

    def test_lte_precondition(self):
        a = GOAPAction(name="lte_test", preconditions={"lte_stock": 5}, effects={"checked": True})
        assert a.is_valid({"stock": 5})
        assert a.is_valid({"stock": 3})
        assert not a.is_valid({"stock": 10})

    def test_ne_precondition(self):
        a = GOAPAction(name="ne_test", preconditions={"ne_status": "shipped"}, effects={"checked": True})
        assert a.is_valid({"status": "pending"})
        assert not a.is_valid({"status": "shipped"})

    def test_in_precondition(self):
        a = GOAPAction(name="in_test", preconditions={"in_category": ["a", "b"]}, effects={"checked": True})
        assert a.is_valid({"category": "a"})
        assert a.is_valid({"category": "b"})
        assert not a.is_valid({"category": "c"})

    def test_mixed_preconditions(self):
        a = GOAPAction(
            name="mixed",
            preconditions={"gt_margin": 0.2, "ne_status": "blocked", "has_item": True},
            effects={"ok": True},
        )
        assert a.is_valid({"margin": 0.25, "status": "active", "has_item": True})
        assert not a.is_valid({"margin": 0.15, "status": "active", "has_item": True})
        assert not a.is_valid({"margin": 0.25, "status": "blocked", "has_item": True})
        assert not a.is_valid({"margin": 0.25, "status": "active", "has_item": False})

    def test_standard_precondition_still_works(self):
        a = GOAPAction(name="std", preconditions={"has_item": True}, effects={"ok": True})
        assert a.is_valid({"has_item": True})
        assert not a.is_valid({"has_item": False})


# ── Compensation / reverse effects ────────────────────────────────────────────

class TestGOAPCompensation:

    def test_inverse_effects(self):
        a = GOAPAction(name="set_flag", effects={"flag": True, "processed": True})
        state = {"flag": False, "processed": False, "other": "keep"}
        inv = a.inverse_effects(state)
        assert "flag" not in inv
        assert "processed" not in inv
        assert inv["other"] == "keep"

    def test_rollback_via_reverse_name(self):
        class SetFlagSkill(Skill):
            name = "set_flag"
            effects = {"flag": True}
            reverse_name = "clear_flag"

        class ClearFlagSkill(Skill):
            name = "clear_flag"
            effects = {"flag": False}

        default_registry.register(SetFlagSkill)
        default_registry.register(ClearFlagSkill)

        planner = GOAPPlanner()
        planner.load_skills(default_registry)
        actions = {a.name: a for a in planner._actions}
        assert "set_flag" in actions
        assert actions["set_flag"].reverse_name == "clear_flag"
        state = {"flag": False}
        inv = actions["set_flag"].inverse_effects(state)
        assert "flag" not in inv


# ── GOAPStateStore ───────────────────────────────────────────────────────────

class TestGOAPStateStore:

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            store = GOAPStateStore(path=str(Path(td) / "state.json"))
            assert store.load() == {}
            store.save({"a": 1, "b": "x"})
            assert store.load() == {"a": 1, "b": "x"}
            store.clear()
            assert store.load() == {}

    def test_load_nonexistent(self):
        store = GOAPStateStore(path="reports/_nonexistent_test_.json")
        assert store.load() == {}
        store.clear()

    def test_save_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            store = GOAPStateStore(path=str(Path(td) / "state.json"))
            store.save({"v": 1})
            store.save({"v": 2})
            assert store.load() == {"v": 2}


# ── Rate Limiter ──────────────────────────────────────────────────────────────

class TestRateLimiter:

    def test_allow_up_to_max(self):
        rl = RateLimiter(max_calls=3, window_seconds=60.0)
        assert rl.allow("test_skill") is True
        assert rl.allow("test_skill") is True
        assert rl.allow("test_skill") is True
        assert rl.allow("test_skill") is False
        assert rl.remaining("test_skill") == 0

    def test_separate_buckets(self):
        rl = RateLimiter(max_calls=2, window_seconds=60.0)
        rl.allow("a")
        rl.allow("a")
        assert rl.allow("a") is False
        assert rl.allow("b") is True
        assert rl.allow("b") is True
        assert rl.allow("b") is False

    def test_window_resets(self):
        rl = RateLimiter(max_calls=2, window_seconds=0.01)
        rl.allow("fast")
        rl.allow("fast")
        assert rl.allow("fast") is False
        time.sleep(0.02)
        assert rl.allow("fast") is True


# ── Sandbox rate limiting integration ─────────────────────────────────────────

def dummy_ok(*_a, **_kw):
    return "ok"


def dummy_fail(*_a, **_kw):
    raise ValueError("fail")


class TestSandboxRateLimit:

    @pytest.mark.asyncio
    async def test_rate_limited_result(self):
        from shopee_agent.skills.sandbox import get_rate_limiter as _grl, run_skill_sandbox as _run
        limiter = _grl()
        limiter._max = 9999  # avoid interference
        from shopee_agent.skills.sandbox import RateLimiter as _RL
        _orig_limiter = _RL(100, 60)
        import shopee_agent.skills.sandbox as _sbx
        _sbx._rate_limiter = _RL(max_calls=0, window_seconds=60)
        result = await _run("rate_test_skill", dummy_ok)
        assert result.get("rate_limited") is True
        assert result.get("ok") is False
        _sbx._rate_limiter = _orig_limiter


# ── External skill discovery ──────────────────────────────────────────────────

class TestExternalSkillDiscovery:

    def test_load_from_external_py_file(self):
        with tempfile.TemporaryDirectory() as td:
            py_path = Path(td) / "external_skill.py"
            py_path.write_text("""
from shopee_agent.skills.registry import Skill

class ExternalTestSkill(Skill):
    name = "external_test"
    preconditions = {"ext_ready": True}
    effects = {"ext_done": True}
    cost = 3.0
    priority = 5
""")
            import importlib.util as _util
            import sys as _sys
            spec = _util.spec_from_file_location("external_skill", str(py_path))
            assert spec is not None and spec.loader is not None
            mod = _util.module_from_spec(spec)
            _sys.modules["external_skill"] = mod
            spec.loader.exec_module(mod)
            cls = getattr(mod, "ExternalTestSkill", None)
            assert cls is not None
            assert cls.name == "external_test"
            assert cls.cost == 3.0
            assert cls.preconditions == {"ext_ready": True}
            default_registry.register(cls)
            instance = default_registry.get_or_create("external_test")
            assert instance is not None
            assert instance.name == "external_test"


# ── Planner can load external-style skills ────────────────────────────────────

class TestPlannerExternalSkills:

    def test_planner_loads_external_skill(self):
        from shopee_agent.skills.registry import SkillRegistry
        registry = SkillRegistry()

        class ExtSkill(Skill):
            name = "ext_skill_op"
            preconditions = {"gt_counter": 0}
            effects = {"ext_done": True}
            cost = 1.5
            priority = 10

        registry.register(ExtSkill)
        planner = GOAPPlanner()
        planner.load_skills(registry)
        names = [a.name for a in planner._actions]
        assert "ext_skill_op" in names
        action = next(a for a in planner._actions if a.name == "ext_skill_op")
        assert action.cost == 1.5
        assert action.priority == 10
        assert action.is_valid({"counter": 5})
        assert not action.is_valid({"counter": 0})
        assert not action.is_valid({"counter": -1})
