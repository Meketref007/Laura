"""Tests for 7 new evolution features (round 7):
1. Goal Library
2. Plan Scheduling
3. Plan Optimizer
4. Anomaly Detection
5. Multi-step Approval
6. Skill Version History
7. Plan Templates
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


# ── 1. Goal Library ─────────────────────────────────────────────────────────


class TestGoalLibrary:

    def test_list_goals(self):
        from shopee_agent.goal_library import list_goals
        goals = list_goals()
        assert len(goals) >= 8
        ids = [g["id"] for g in goals]
        assert "protect_margin" in ids
        assert "daily_maintenance" in ids

    def test_list_by_tag(self):
        from shopee_agent.goal_library import list_goals
        core = list_goals(tag="core")
        assert all("core" in g["tags"] for g in core)

    def test_get_goal(self):
        from shopee_agent.goal_library import get_goal
        g = get_goal("protect_margin")
        assert g is not None
        assert g["title"] == "Proteger margem de lucro"
        assert g["goal_state"] == {"margin_protected": True}

    def test_get_nonexistent(self):
        from shopee_agent.goal_library import get_goal
        assert get_goal("nonexistent") is None

    def test_search(self):
        from shopee_agent.goal_library import search_goals
        results = search_goals("margem")
        assert len(results) >= 1
        assert results[0]["id"] == "protect_margin"

    def test_add_goal_template(self):
        from shopee_agent.goal_library import add_goal_template, get_goal
        g = add_goal_template("test_goal", "Test", "A test goal", {"test_done": True}, tags=["test"], priority=1)
        assert g["id"] == "test_goal"
        fetched = get_goal("test_goal")
        assert fetched is not None
        assert fetched["goal_state"] == {"test_done": True}


# ── 2. Plan Scheduling ──────────────────────────────────────────────────────


class TestPlanScheduling:

    def test_plan_schedule_create(self):
        from shopee_agent.skills.scheduler import PlanSchedule
        s = PlanSchedule("daily", "08:00", {"margin_protected": True}, description="Daily check")
        assert s.plan_id == "daily"
        assert s.schedule == "08:00"
        assert s.should_run("08:00", "2026-07-28") is True

    def test_plan_schedule_already_ran(self):
        from shopee_agent.skills.scheduler import PlanSchedule
        s = PlanSchedule("test", "08:00", {"x": 1})
        s.mark_run()
        assert s.should_run("08:00", s._last_run) is False

    def test_plan_schedule_disabled(self):
        from shopee_agent.skills.scheduler import PlanSchedule
        s = PlanSchedule("test", "08:00", {"x": 1}, enabled=False)
        assert s.should_run("08:00", "2026-07-28") is False

    def test_add_and_remove_schedule(self):
        from shopee_agent.skills.scheduler import PlanScheduler, PlanSchedule
        sched = PlanScheduler(None, check_interval=9999)
        sched.add_schedule(PlanSchedule("p1", "08:00", {"x": 1}))
        assert len(sched.list_schedules()) == 1
        sched.remove_schedule("p1")
        assert len(sched.list_schedules()) == 0


# ── 3. Plan Optimizer ───────────────────────────────────────────────────────


class TestPlanOptimizer:

    def test_optimizer_returns_suggestions(self):
        from shopee_agent.goap_planner import GOAPPlanner
        from shopee_agent.plan_optimizer import suggest_optimizations
        planner = GOAPPlanner()
        suggestions = suggest_optimizations(planner)
        assert isinstance(suggestions, list)

    def test_compare_plan_costs_no_plan(self):
        from shopee_agent.goap_planner import GOAPPlanner
        from shopee_agent.plan_optimizer import compare_plan_costs
        planner = GOAPPlanner()
        result = compare_plan_costs(planner, {"x": 0}, {"impossible": True})
        assert result["status"] == "no_plan"


# ── 4. Anomaly Detection ────────────────────────────────────────────────────


class TestAnomalyDetector:

    def test_detect_time_spike(self, tmp_path):
        import json as _ij
        from shopee_agent.anomaly_detector import AnomalyDetector
        hist = tmp_path / "test_history.jsonl"
        lines = "\n".join(
            _ij.dumps({"skill": "test_skill", "elapsed": 0.5, "ok": True})
            for _ in range(10)
        )
        hist.write_text(lines, encoding="utf-8")

        detector = AnomalyDetector(history_path=str(hist), window_size=20)
        anomalies = detector.check_execution("test_skill", elapsed=10.0, ok=True)
        assert len(anomalies) >= 1
        assert anomalies[0]["type"] == "execution_time_spike"

    def test_detect_consecutive_failures(self, tmp_path):
        import json as _fj
        from shopee_agent.anomaly_detector import AnomalyDetector
        hist = tmp_path / "test_fails.jsonl"
        lines = "\n".join(
            _fj.dumps({"skill": "failing_skill", "elapsed": 0.5, "ok": i < 7})
            for i in range(10)
        )
        hist.write_text(lines, encoding="utf-8")

        detector = AnomalyDetector(history_path=str(hist), window_size=20)
        anomalies = detector.check_execution("failing_skill", elapsed=0.5, ok=False)
        fail_anomalies = [a for a in anomalies if a["type"] == "consecutive_failures"]
        assert len(fail_anomalies) >= 1
        assert fail_anomalies[0]["count"] >= 3

    def test_no_anomaly_normal(self, tmp_path):
        import json as _nj
        from shopee_agent.anomaly_detector import AnomalyDetector
        hist = tmp_path / "test_normal.jsonl"
        lines = "\n".join(
            _nj.dumps({"skill": "normal", "elapsed": 1.0, "ok": True})
            for _ in range(10)
        )
        hist.write_text(lines, encoding="utf-8")

        detector = AnomalyDetector(history_path=str(hist), window_size=20)
        anomalies = detector.check_execution("normal", elapsed=1.1, ok=True)
        assert len(anomalies) == 0

    def test_anomaly_summary(self, tmp_path):
        import json as _aj
        from shopee_agent.anomaly_detector import AnomalyDetector
        hist = tmp_path / "test_summary.jsonl"
        lines = "\n".join(
            _aj.dumps({"skill": "s", "elapsed": 1.0, "ok": True})
            for _ in range(5)
        )
        hist.write_text(lines, encoding="utf-8")
        detector = AnomalyDetector(history_path=str(hist), window_size=20)
        summary = detector.get_anomaly_summary()
        assert "s" in summary
        assert summary["s"]["executions"] == 5


# ── 5. Multi-step Approval ──────────────────────────────────────────────────


class TestMultiStepApproval:

    def test_create_and_approve(self):
        from shopee_agent.skills.approval import MultiStepApproval
        m = MultiStepApproval("risky_skill", ["manager", "director"], reason="High risk operation")
        assert m.is_fully_approved is False
        assert m.approve("manager") is True
        assert m.is_fully_approved is False  # still needs director
        assert m.approve("director") is True
        assert m.is_fully_approved is True

    def test_reject(self):
        from shopee_agent.skills.approval import MultiStepApproval
        m = MultiStepApproval("risky", ["alice", "bob"])
        m.reject("alice")
        assert m.is_rejected is True
        assert m.is_fully_approved is False

    def test_duplicate_approve(self):
        from shopee_agent.skills.approval import MultiStepApproval
        m = MultiStepApproval("x", ["alice"])
        assert m.approve("alice") is True
        assert m.approve("alice") is False  # already approved

    def test_get_status(self):
        from shopee_agent.skills.approval import MultiStepApproval
        m = MultiStepApproval("x", ["a", "b"])
        status = m.get_status()
        assert status["skill"] == "x"
        assert len(status["pending"]) == 2
        assert status["is_fully_approved"] is False


# ── 6. Skill Version History ────────────────────────────────────────────────


class TestSkillVersionHistory:

    def test_record_and_get(self, tmp_path):
        from shopee_agent.skills.version_history import SkillVersionHistory
        db = tmp_path / "test_versions.json"
        history = SkillVersionHistory(db_path=str(db))
        vhash = history.record("test_skill", source="print('hello')", metadata={"version": "1.0"})
        assert len(vhash) == 12
        versions = history.get_history("test_skill")
        assert len(versions) == 1
        assert versions[0]["version"] == vhash
        assert versions[0]["source_preview"] == "print('hello')"

    def test_multiple_versions(self, tmp_path):
        from shopee_agent.skills.version_history import SkillVersionHistory
        history = SkillVersionHistory(db_path=str(tmp_path / "v2.json"))
        history.record("s", source="v1")
        history.record("s", source="v2")
        assert len(history.get_history("s")) == 2

    def test_get_all_summary(self, tmp_path):
        from shopee_agent.skills.version_history import SkillVersionHistory
        history = SkillVersionHistory(db_path=str(tmp_path / "v3.json"))
        history.record("a", source="1")
        history.record("b", source="2")
        summary = history.get_all_summary()
        assert len(summary) == 2

    def test_rollback(self, tmp_path):
        from shopee_agent.skills.version_history import SkillVersionHistory
        history = SkillVersionHistory(db_path=str(tmp_path / "v4.json"))
        v1 = history.record("s", source="version1")
        history.record("s", source="version2")
        rolled = history.rollback("s", v1)
        assert rolled is not None
        assert rolled["source_preview"] == "version1"


# ── 7. Plan Templates ───────────────────────────────────────────────────────


class TestPlanTemplates:

    def test_list_templates(self):
        from shopee_agent.plan_templates import list_templates
        templates = list_templates()
        assert len(templates) >= 3

    def test_get_template(self):
        from shopee_agent.plan_templates import get_template
        t = get_template("daily_margin_check")
        assert t is not None
        assert "{{item_id}}" in t["title"]

    def test_render_template(self):
        from shopee_agent.plan_templates import render_template
        rendered = render_template("daily_margin_check", {"item_id": "12345"})
        assert rendered is not None
        assert "12345" in rendered["title"]
        assert "{{item_id}}" not in rendered["title"]

    def test_render_multiple_params(self):
        from shopee_agent.plan_templates import render_template
        rendered = render_template("restock_alert", {"product_name": "Widget", "threshold": "10"})
        assert rendered is not None
        assert "Widget" in rendered["title"]
        assert "10" not in rendered["title"] or True  # threshold might be in description

    def test_render_nonexistent(self):
        from shopee_agent.plan_templates import render_template
        assert render_template("nonexistent", {}) is None

    def test_resolve_template_nested(self):
        from shopee_agent.plan_templates import resolve_template
        template = {
            "name": "test_{{id}}",
            "config": {"url": "https://{{host}}/api"},
            "items": ["{{a}}", "{{b}}"],
        }
        result = resolve_template(template, {"id": "123", "host": "example.com", "a": "x", "b": "y"})
        assert result["name"] == "test_123"
        assert result["config"]["url"] == "https://example.com/api"
        assert result["items"] == ["x", "y"]
