"""Tests for SkillOrchestrator, GOAP integration, and CLI skill commands."""

import json
import pytest
from unittest.mock import MagicMock, patch
from shopee_agent.skills.orchestrator import SkillOrchestrator
from shopee_agent.skills.registry import Skill, SkillRegistry, default_registry
from shopee_agent.skills.loader import discover_and_register


class TestSkillOrchestrator:

    def setup_method(self):
        discover_and_register()

    def test_determine_skills_finds_plan(self):
        orch = SkillOrchestrator()
        skills = orch.determine_skills(
            {"stock_checked": False, "margin_protected": False},
            {"stock_checked": True, "margin_protected": True},
            max_depth=6,
        )
        assert len(skills) > 0
        assert isinstance(skills, list)

    def test_determine_skills_no_plan_when_already_done(self):
        orch = SkillOrchestrator()
        skills = orch.determine_skills(
            {"stock_checked": True, "margin_protected": True},
            {"stock_checked": True, "margin_protected": True},
            max_depth=4,
        )
        assert skills == []

    def test_execute_plan_runs_skills(self):
        orch = SkillOrchestrator()
        results = orch.execute_plan(
            ["low_stock_alert", "protect_margin"],
            context={"item_id": "test123", "stock": 1, "threshold": 3},
        )
        assert len(results) == 2
        for r in results:
            assert "ok" in r

    def test_execute_plan_unknown_skill(self):
        orch = SkillOrchestrator()
        results = orch.execute_plan(["nonexistent_skill"])
        assert len(results) == 1
        assert results[0]["ok"] is False
        assert results[0]["error"] == "not_found"

    def test_evaluate_state_full_flow(self):
        orch = SkillOrchestrator()
        result = orch.evaluate_state(
            {"stock_checked": False, "margin_protected": False},
            {"stock_checked": True, "margin_protected": True},
            max_depth=4,
        )
        assert result["status"] in ("executed", "no_plan")

    def test_history_is_appended(self, tmp_path):
        history = tmp_path / "skill_history.jsonl"
        orch = SkillOrchestrator(history_path=str(history))
        orch._append_history("test_skill", ok=True, result="ok")
        lines = history.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["skill"] == "test_skill"
        assert entry["ok"] is True

    def test_orchestrator_uses_custom_registry(self):
        reg = SkillRegistry()

        class TestSkill(Skill):
            name = "test_custom"
            def run(self, **kwargs):
                return {"done": True}

        reg.register(TestSkill)
        orch = SkillOrchestrator(registry=reg)
        orch._planner._actions = []
        from shopee_agent.goap_planner import GOAPAction
        orch._planner.register_action(GOAPAction(
            name="test_custom",
            cost=1.0,
            preconditions={"need_test": True},
            effects={"need_test": False},
        ))
        skills = orch.determine_skills(
            {"need_test": True},
            {"need_test": False},
        )
        assert skills == ["test_custom"]


class TestExecutorSkillRouting:

    def test_executor_routes_to_skill_via_metadata(self):
        from shopee_agent.decision_integration import DecisionExecutor
        from shopee_agent.decision_engine import Decision, DecisionType, DecisionPriority, DecisionStatus
        from datetime import datetime, timezone

        executor = DecisionExecutor(store_id="test")
        executor._get_client = MagicMock()
        executor._get_tokens = MagicMock(return_value=("token", 1))

        sig = __import__("shopee_agent.decision_engine", fromlist=["DecisionSignal"]).DecisionSignal(
            source="test", signal_type="routine", data={}
        )
        d = Decision(
            decision_id="skill_test_1",
            title="Test skill decision",
            decision_type=DecisionType.ALERTS,
            recommended_action="run pricing",
            priority=DecisionPriority.LOW,
            status=DecisionStatus.APPROVED,
            metadata={"skill": "low_stock_alert", "item_id": "test", "stock": 1, "threshold": 3},
            created_at=datetime.now(timezone.utc),
            rule_id="test_rule",
            description="test",
            impact_score=0.5,
            risk_score=0.1,
            confidence_score=0.9,
            signal=sig,
        )
        result = executor.execute(d)
        assert result is True

    def test_executor_fallback_when_skill_unknown(self):
        from shopee_agent.decision_integration import DecisionExecutor
        from shopee_agent.decision_engine import Decision, DecisionType, DecisionPriority, DecisionStatus, DecisionSignal
        from datetime import datetime, timezone

        executor = DecisionExecutor(store_id="test")

        sig = DecisionSignal(source="test", signal_type="routine", data={})
        d = Decision(
            decision_id="skill_test_2",
            title="Fallback test",
            decision_type=DecisionType.PRICING,
            recommended_action="",
            priority=DecisionPriority.LOW,
            status=DecisionStatus.APPROVED,
            metadata={"skill": "nonexistent_skill_xyz"},
            created_at=datetime.now(timezone.utc),
            rule_id="test_rule",
            description="test",
            impact_score=0.0,
            risk_score=0.0,
            confidence_score=0.0,
            signal=sig,
        )
        result = executor.execute(d)
        assert result is False

    def test_executor_type_dispatch_still_works(self):
        from shopee_agent.decision_integration import DecisionExecutor
        from shopee_agent.decision_engine import Decision, DecisionType, DecisionPriority, DecisionStatus, DecisionSignal
        from datetime import datetime, timezone

        executor = DecisionExecutor(store_id="test")
        executor._get_client = MagicMock()
        executor._get_tokens = MagicMock(return_value=("token", 1))

        sig = DecisionSignal(source="test", signal_type="routine", data={})
        d = Decision(
            decision_id="type_test_1",
            title="Type dispatch test",
            decision_type=DecisionType.ALERTS,
            recommended_action="test alert",
            priority=DecisionPriority.LOW,
            status=DecisionStatus.APPROVED,
            metadata={},
            created_at=datetime.now(timezone.utc),
            rule_id="test_rule",
            description="test",
            impact_score=0.0,
            risk_score=0.0,
            confidence_score=0.0,
            signal=sig,
        )
        result = executor.execute(d)
        assert result is True
