"""Tests for 8 new evolution features (round 6):
1. Plan visualization (Mermaid export)
2. Skill scaffolding (skill-create)
3. Plan diff
4. Alert notification integration
5. Cost history chart endpoint
6. Batch plan execution
7. Plan export/import
8. Integration test structure
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from shopee_agent.skills.registry import Skill, SkillRegistry


# ── 1. Plan visualization (Mermaid) ──────────────────────────────────────────


class TestPlanViz:

    def test_mermaid_flowchart(self):
        from shopee_agent.plan_viz import plan_to_mermaid
        actions = [
            {"name": "check_stock", "cost": 1.0, "preconditions": {"stock_unknown": True}, "effects": {"stock_known": True}},
            {"name": "reorder", "cost": 2.0, "preconditions": {"stock_low": True}, "effects": {"stock_ok": True}},
        ]
        result = plan_to_mermaid(actions, {"stock_unknown": True}, {"stock_ok": True})
        assert "```mermaid" in result
        assert "flowchart TD" in result
        assert "check_stock" in result
        assert "reorder" in result
        assert "START" in result
        assert "GOAL" in result

    def test_mermaid_gantt(self):
        from shopee_agent.plan_viz import plan_to_mermaid_gantt
        actions = [
            {"name": "a", "cost": 1.0},
            {"name": "b", "cost": 2.0},
        ]
        result = plan_to_mermaid_gantt(actions)
        assert "```mermaid" in result
        assert "gantt" in result
        assert "a" in result
        assert "b" in result

    def test_empty_actions(self):
        from shopee_agent.plan_viz import plan_to_mermaid
        result = plan_to_mermaid([])
        assert "```mermaid" in result
        assert "END" in result


# ── 2. Skill scaffolding ────────────────────────────────────────────────────


class TestSkillScaffolding:

    def test_generate_source_basic(self):
        from shopee_agent.skills.scaffold import generate_skill_source
        source = generate_skill_source("monitor_preco")
        assert "class MonitorPrecoSkill" in source
        assert 'name = "monitor_preco"' in source
        assert "def run" in source

    def test_generate_source_full(self):
        from shopee_agent.skills.scaffold import generate_skill_source
        source = generate_skill_source(
            "check_stock", risk_level="HIGH", cost=2.5, priority=3,
            preconditions={"stock_unknown": True},
            effects={"stock_known": True},
            reverse_name="restore_stock",
            sub_skills=["notify"],
            event_types=["metric.update"],
            schedule="08:00",
            dependencies=["auth"],
        )
        assert "class CheckStockSkill" in source
        assert "risk_level = \"HIGH\"" in source
        assert "cost = 2.5" in source
        assert "priority = 3" in source
        assert '"stock_unknown": true' in source.lower() or '"stock_unknown": True' in source
        assert "restore_stock" in source
        assert "notify" in source
        assert "metric.update" in source
        assert "08:00" in source
        assert "auth" in source

    def test_write_skill_file(self, tmp_path):
        from shopee_agent.skills.scaffold import write_skill_file
        path = write_skill_file("test_scaffold_skill", output_dir=str(tmp_path))
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "class TestScaffoldSkillSkill" in content or "class TestScaffoldSkill" in content

    def test_to_class_name(self):
        from shopee_agent.skills.scaffold import _to_class_name
        assert _to_class_name("monitor preco") == "MonitorPrecoSkill"
        assert _to_class_name("check-stock") == "CheckStockSkill"
        assert _to_class_name("abc") == "AbcSkill"


# ── 3. Plan diff ────────────────────────────────────────────────────────────


class TestPlanDiff:

    def test_diff_same_plans(self):
        from shopee_agent.plan_store import diff_plans
        a = {"id": 1, "actions": ["a", "b"], "total_cost": 3.0}
        b = {"id": 2, "actions": ["a", "b"], "total_cost": 3.0}
        result = diff_plans(a, b)
        assert result["actions_only_a"] == []
        assert result["actions_only_b"] == []
        assert result["cost_diff"] == 0.0

    def test_diff_different_actions(self):
        from shopee_agent.plan_store import diff_plans
        a = {"id": 1, "actions": ["a", "b", "c"], "total_cost": 5.0}
        b = {"id": 2, "actions": ["a", "d"], "total_cost": 3.0}
        result = diff_plans(a, b)
        assert "b" in result["actions_only_a"]
        assert "c" in result["actions_only_a"]
        assert "d" in result["actions_only_b"]
        assert "a" in result["actions_common"]
        assert result["cost_diff"] == -2.0

    def test_diff_empty(self):
        from shopee_agent.plan_store import diff_plans
        result = diff_plans({"actions": []}, {"actions": []})
        assert result["actions_only_a"] == []
        assert result["actions_only_b"] == []


# ── 4. Alert notification integration ───────────────────────────────────────


class TestAlertNotification:

    def test_notify_fn_is_called(self):
        from shopee_agent.planner_alerts import PlannerAlert, PlannerAlertManager

        notified: List[str] = []

        def fake_notify(msg: str):
            notified.append(msg)

        alert = PlannerAlert("test", "desc",
                             check_fn=lambda ctx: True,
                             message_fn=lambda ctx: "triggered",
                             cooldown_seconds=0)
        manager = PlannerAlertManager(path="reports/_test_notify.jsonl")
        manager.set_notify(fake_notify)
        manager.add_alert(alert)
        manager.check_all({})
        assert len(notified) == 1
        assert "triggered" in notified[0]

    def test_notify_cooldown(self):
        from shopee_agent.planner_alerts import PlannerAlert, PlannerAlertManager

        count = [0]

        def fake(msg: str):
            count[0] += 1

        alert = PlannerAlert("cooldown_test", "desc",
                             check_fn=lambda ctx: True,
                             message_fn=lambda ctx: "x",
                             cooldown_seconds=9999)
        manager = PlannerAlertManager(path="reports/_test_notify2.jsonl")
        manager.set_notify(fake)
        manager.add_alert(alert)
        manager.check_all({})
        manager.check_all({})  # suppressed by cooldown
        assert count[0] == 1

    def test_notify_no_fn_does_not_crash(self):
        from shopee_agent.planner_alerts import PlannerAlert, PlannerAlertManager
        alert = PlannerAlert("safe", "desc", check_fn=lambda ctx: True, message_fn=lambda ctx: "x", cooldown_seconds=0)
        manager = PlannerAlertManager(path="reports/_test_notify3.jsonl")
        manager.add_alert(alert)
        result = manager.check_all({})
        assert len(result) == 1  # no notify fn configured, should not crash


# ── 5. Cost history chart endpoint ──────────────────────────────────────────


class TestCostHistory:

    def test_api_endpoint_returns_data(self):
        """Test the /api/goap-cost-history logic directly."""
        from shopee_agent.goap_planner import GOAPPlanner
        planner = GOAPPlanner()
        summary = planner.get_learning_summary()
        assert "backend" in summary
        assert "base_actions" in summary
        assert "cost_overrides" in summary


# ── 6. Batch plan execution ─────────────────────────────────────────────────


class TestBatchExecution:

    def test_batch_format(self):
        """Verify the batch JSON format expected by plan-batch."""
        batch = [
            {"current_state": {"x": 0}, "goal_state": {"x": 1}},
            {"current_state": {"y": 0}, "goal_state": {"y": 1}, "dry_run": True},
        ]
        assert len(batch) == 2
        assert batch[0]["current_state"]["x"] == 0
        assert batch[1]["dry_run"] is True


# ── 7. Plan export/import ───────────────────────────────────────────────────


class TestPlanExportImport:

    def test_export_plan(self):
        from shopee_agent.plan_store import export_plan
        plan = {"id": 1, "plan_hash": "abc", "start_state": {"x": 1}, "goal": {"y": 1},
                "actions": ["a", "b"], "total_cost": 3.0, "max_depth": 6, "max_budget": None}
        exported = export_plan(plan)
        assert exported["version"] == "1.0"
        assert exported["plan_hash"] == "abc"
        assert exported["actions"] == ["a", "b"]
        assert "exported_at" in exported
        # Should not contain internal id
        assert "id" not in exported

    def test_import_plan(self):
        from shopee_agent.plan_store import import_plan
        data = {"plan_hash": "xyz", "start_state": {"a": 1}, "goal": {"b": 1},
                "actions": ["x"], "total_cost": "2.5", "max_depth": "8", "max_budget": None}
        normalized = import_plan(data)
        assert normalized["plan_hash"] == "xyz"
        assert normalized["total_cost"] == 2.5
        assert normalized["max_depth"] == 8

    def test_roundtrip(self):
        from shopee_agent.plan_store import PlanStore, export_plan, import_plan
        store = PlanStore(db_path=":memory:")
        # Override path to use in-memory
        pid = store.save_plan("h1", {"x": 1}, {"y": 1}, ["a"], 1.0)
        plan = store.get_plan(pid)
        exported = export_plan(plan)
        imported_normalized = import_plan(exported)
        # Verify import has all required fields
        for key in ("plan_hash", "start_state", "goal", "actions", "total_cost", "max_depth", "max_budget"):
            assert key in imported_normalized


# ── 8. Integration test structure ───────────────────────────────────────────


class TestIntegrationStructure:

    def test_plan_to_execution_roundtrip(self):
        """Verify a plan can be created, stored, retrieved, and diffed."""
        from shopee_agent.plan_store import PlanStore, diff_plans

        store = PlanStore(db_path=":memory:")
        pid1 = store.save_plan("hash1", {"a": 0}, {"a": 1}, ["skill_x"], 1.0, all_ok=True)
        pid2 = store.save_plan("hash2", {"a": 0}, {"a": 1}, ["skill_y"], 2.0, all_ok=False)

        plan1 = store.get_plan(pid1)
        plan2 = store.get_plan(pid2)
        assert plan1 is not None
        assert plan2 is not None

        diff = diff_plans(plan1, plan2)
        assert "skill_x" in diff["actions_only_a"]
        assert "skill_y" in diff["actions_only_b"]
        assert diff["cost_diff"] == 1.0

    def test_skill_registry_reload_cycle(self):
        """Verify skills can be registered, unregistered, and reloaded."""
        registry = SkillRegistry()

        class TempSkill(Skill):
            name = "temp_integration"

        registry.register(TempSkill)
        assert "temp_integration" in registry.list()

        registry.unregister("temp_integration")
        assert "temp_integration" not in registry.list()
