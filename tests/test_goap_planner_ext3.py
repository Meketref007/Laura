"""Tests for: event triggers, approval, scheduler, multi-store, goal NL, benchmark."""

import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from shopee_agent.skills.event_triggers import (
    register_trigger, get_triggers, list_all_triggers, set_triggers_from_metadata,
)
from shopee_agent.skills.approval import (
    request_approval, approve, reject, is_approved, is_rejected, list_pending, list_all, approve_all_pending,
)
from shopee_agent.skills.scheduler import SkillScheduler
from shopee_agent.skills.store_registry import StoreRegistry, StoreContext
from shopee_agent.skills.goal_nl import synthesize_from_text, synthesize_with_llm
from shopee_agent.skills.registry import Skill, SkillRegistry


# ── Event-driven skill triggers ──────────────────────────────────────────────

class TestEventTriggers:

    def test_register_and_get(self):
        register_trigger("order.placed", "ShipOrderSkill")
        register_trigger("refund.created", "RefundSkill")
        assert "ShipOrderSkill" in get_triggers("order.placed")
        assert "RefundSkill" in get_triggers("refund.created")
        assert get_triggers("unknown.event") == []

    def test_list_all(self):
        triggers = list_all_triggers()
        assert isinstance(triggers, dict)

    def test_set_from_metadata(self):
        registry = SkillRegistry()

        class AutoShip(Skill):
            name = "auto_ship"
            event_types = ["order.placed"]

        class AutoRefund(Skill):
            name = "auto_refund"
            event_types = ["refund.created", "order.cancelled"]

        registry.register(AutoShip)
        registry.register(AutoRefund)
        set_triggers_from_metadata(registry)
        assert "auto_ship" in get_triggers("order.placed")
        assert "auto_refund" in get_triggers("refund.created")
        assert "auto_refund" in get_triggers("order.cancelled")


# ── Human-in-the-loop approval ──────────────────────────────────────────────

class TestApproval:

    def test_request_and_approve(self):
        rid = request_approval("HighRiskSkill", reason="test")
        assert rid
        # starts as pending, not yet approved
        assert is_approved(rid) is False
        assert approve(rid) is True
        assert is_approved(rid) is True

    def test_request_and_reject(self):
        rid = request_approval("AnotherHighRisk")
        assert reject(rid) is True
        assert is_rejected(rid) is True
        assert is_approved(rid) is False

    def test_list_pending(self):
        request_approval("ListTestSkill")
        pending = list_pending()
        assert any(r["skill"] == "ListTestSkill" for r in pending)

    def test_approve_all_pending(self):
        request_approval("BulkSkill1")
        request_approval("BulkSkill2")
        count = approve_all_pending()
        assert count >= 2

    def test_approve_twice_fails(self):
        rid = request_approval("DoubleApprove")
        assert approve(rid) is True
        assert approve(rid) is False  # already approved


# ── Scheduled execution ──────────────────────────────────────────────────────

class TestScheduler:

    def test_schedule_parsing(self):
        registry = SkillRegistry()

        class DailySkill(Skill):
            name = "daily_task"
            schedule = "08:00"

        registry.register(DailySkill)
        scheduler = SkillScheduler(registry=registry, runner=lambda x: x)
        status = scheduler.status()
        assert len(status) == 1
        assert status[0]["skill"] == "daily_task"
        assert status[0]["schedule"] == "08:00"

    def test_no_schedule(self):
        registry = SkillRegistry()

        class NoSchedule(Skill):
            name = "no_schedule"

        registry.register(NoSchedule)
        scheduler = SkillScheduler(registry=registry, runner=lambda x: x)
        assert scheduler.status() == []


# ── Multi-store / multi-tenant ──────────────────────────────────────────────

class TestMultiStore:

    def test_store_registry(self):
        reg = StoreRegistry()
        ctx1 = reg.get_or_create("store_a")
        ctx2 = reg.get_or_create("store_b")
        assert ctx1.store_id == "store_a"
        assert ctx2.store_id == "store_b"
        assert ctx1 is not ctx2

    def test_store_isolated_planners(self):
        reg = StoreRegistry()
        ctx_a = reg.get_or_create("store_a")
        ctx_b = reg.get_or_create("store_b")
        # Each has its own learning path
        assert "store_a" in str(ctx_a.planner._learning_path)
        assert "store_b" in str(ctx_b.planner._learning_path)

    def test_store_summaries(self):
        reg = StoreRegistry()
        reg.get_or_create("store_x")
        reg.get_or_create("store_y")
        summaries = reg.summaries()
        assert "store_x" in summaries
        assert "store_y" in summaries

    def test_store_context_metadata(self):
        ctx = StoreContext("test_store")
        ctx.metadata["region"] = "BR"
        assert ctx.summary()["metadata"]["region"] == "BR"


# ── Natural language goal input ─────────────────────────────────────────────

class TestGoalNL:

    def test_margin_keyword(self):
        goal = synthesize_from_text("precisa aumentar margem")
        assert goal.get("margin_protected") is True

    def test_stock_keyword(self):
        goal = synthesize_from_text("repor estoque urgente")
        assert goal.get("stock_checked") is True

    def test_full_keyword(self):
        goal = synthesize_from_text("fazer tudo")
        assert "margin_protected" in goal
        assert "stock_checked" in goal
        assert "prices_optimized" in goal
        assert "support_handled" in goal

    def test_monitor_keyword(self):
        goal = synthesize_from_text("só monitorar")
        assert goal.get("monitor_ok") is True

    def test_fallback_llm(self):
        # When no LLM provided, falls back to keywords
        goal = synthesize_with_llm("margem baixa", llm_func=None)
        assert goal.get("margin_protected") is True

    def test_llm_with_mock(self):
        def mock_llm(prompt: str) -> str:
            return '{"stock_checked": true, "prices_optimized": true}'
        goal = synthesize_with_llm("qualquer coisa", llm_func=mock_llm)
        assert goal.get("stock_checked") is True
        assert goal.get("prices_optimized") is True

    def test_empty_text(self):
        goal = synthesize_from_text("")
        assert goal


# ── Benchmark ────────────────────────────────────────────────────────────────

class TestBenchmark:

    def test_goap_planner_benchmark(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
        import time as _t
        planner = GOAPPlanner()
        planner.register_action(GOAPAction("a", cost=1.0, effects={"x": True}))
        planner.register_action(GOAPAction("b", cost=2.0, preconditions={"x": True}, effects={"y": True}))
        times = []
        for _ in range(5):
            t0 = _t.perf_counter()
            planner.plan({"x": False, "y": False}, {"y": True}, use_cache=False)
            times.append((_t.perf_counter() - t0) * 1000)
        mean = sum(times) / len(times)
        assert mean >= 0  # just ensure it runs without error
        assert len(times) == 5
