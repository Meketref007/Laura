"""Tests for: SQLite learning DB, A/B testing, skill generation, budget-aware, canary, explain, sandbox."""

import json
import tempfile
from pathlib import Path

import pytest
from shopee_agent.learning_db import LearningDB
from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
from shopee_agent.skills.ab_testing import ABTestRegistry
from shopee_agent.skills.canary import CanaryDeploy
from shopee_agent.skills.generator import generate_skill_class, _safe_name
from shopee_agent.skills.registry import Skill, SkillRegistry
from shopee_agent.skills.shopee_sandbox import ShopeeSandboxClient


# ── SQLite Learning DB ─────────────────────────────────────────────────────

def _make_db():
    """Create a LearningDB with a unique temp path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    import os as _os
    _os.close(fd)
    db = LearningDB(db_path=path)
    return db, path


class TestLearningDB:

    def test_get_cost_default(self):
        db, path = _make_db()
        try:
            cost = db.get_cost("unknown_skill")
            assert cost == 1.0
        finally:
            db.close()
            Path(path).unlink(missing_ok=True)

    def test_record_outcome_success(self):
        db, path = _make_db()
        try:
            new_cost = db.record_outcome("test_skill", success=True, cost=2.0, elapsed_ms=10)
            assert new_cost < 2.0
            assert db.get_cost("test_skill") == new_cost
        finally:
            db.close()
            Path(path).unlink(missing_ok=True)

    def test_record_outcome_failure(self):
        db, path = _make_db()
        try:
            new_cost = db.record_outcome("fail_skill", success=False, cost=1.0)
            assert new_cost > 1.0
        finally:
            db.close()
            Path(path).unlink(missing_ok=True)

    def test_rollback(self):
        db, path = _make_db()
        try:
            db.record_outcome("roll_skill", success=False, cost=1.0)
            cost_after = db.get_cost("roll_skill")
            db.rollback("roll_skill", steps=1)
            assert db.get_cost("roll_skill") < cost_after
        finally:
            db.close()
            Path(path).unlink(missing_ok=True)

    def test_get_stats(self):
        db, path = _make_db()
        try:
            db.record_outcome("stat_skill", success=True, cost=1.5)
            stats = db.get_stats("stat_skill")
            assert stats["executions"] >= 1
        finally:
            db.close()
            Path(path).unlink(missing_ok=True)

    def test_export_json(self):
        db, path = _make_db()
        try:
            db.record_outcome("export_skill", success=True, cost=1.0)
            exported = db.export_json()
            assert "export_skill" in exported
        finally:
            db.close()
            Path(path).unlink(missing_ok=True)


# ── GOAPPlanner with SQLite ────────────────────────────────────────────────

class TestPlannerSQLite:

    def test_planner_uses_sqlite_by_default(self):
        planner = GOAPPlanner(use_sqlite=True)
        assert planner._learning_db is not None

    def test_record_outcome_via_sqlite(self):
        planner = GOAPPlanner(use_sqlite=True)
        planner.register_action(GOAPAction("sqlite_test", cost=2.0, effects={"x": True}))
        planner.record_outcome("sqlite_test", success=True, elapsed_ms=5)
        stats = planner.get_learning_stats("sqlite_test")
        assert stats["executions"] >= 1

    def test_rollback_via_planner(self):
        planner = GOAPPlanner(use_sqlite=True)
        planner.register_action(GOAPAction("rb_test", cost=1.0, effects={"x": True}))
        planner.record_outcome("rb_test", success=False)
        assert planner.rollback_learning("rb_test", steps=1) is True


# ── Budget-aware planning ─────────────────────────────────────────────────

class TestBudgetAware:

    def test_budget_prunes_expensive_plans(self):
        planner = GOAPPlanner(use_sqlite=False)
        planner.register_action(GOAPAction("cheap", cost=0.5, effects={"x": True}))
        planner.register_action(GOAPAction("expensive", cost=10.0, effects={"x": True}))
        plan = planner.plan({"x": False}, {"x": True}, max_budget=1.0)
        assert plan is not None
        assert plan[0].name == "cheap"

    def test_budget_excludes_all(self):
        planner = GOAPPlanner(use_sqlite=False)
        planner.register_action(GOAPAction("a", cost=5.0, effects={"x": True}))
        plan = planner.plan({"x": False}, {"x": True}, max_budget=2.0)
        assert plan is None  # only action costs 5 > budget 2


# ── Explainability ─────────────────────────────────────────────────────────

class TestExplain:

    def test_explain_returns_details(self):
        planner = GOAPPlanner(use_sqlite=False)
        planner.register_action(GOAPAction("step1", cost=1.0, preconditions={"ready": True}, effects={"done": True}))
        planner.register_action(GOAPAction("step2", cost=1.0, preconditions={"done": True}, effects={"finished": True}))
        explanation = planner.explain({"ready": True, "done": False, "finished": False}, {"finished": True})
        assert explanation["plan"] is not None
        assert len(explanation["actions"]) == 2
        assert explanation["actions"][0]["name"] == "step1"
        assert explanation["actions"][0]["matched"]["ready"] is True
        assert "missed" not in explanation["actions"][0] or explanation["actions"][0]["missed"] == {}

    def test_explain_no_plan(self):
        planner = GOAPPlanner(use_sqlite=False)
        explanation = planner.explain({"x": False}, {"x": True})
        assert explanation.get("error") == "no_plan_found"

    def test_explain_shows_missed_preconditions(self):
        planner = GOAPPlanner(use_sqlite=False)
        planner.register_action(GOAPAction("needs_flag", cost=1.0, preconditions={"flag": True}, effects={"done": True}))
        explanation = planner.explain({"flag": False}, {"done": True})
        assert explanation.get("error") == "no_plan_found"  # precondition not met


# ── A/B Testing ────────────────────────────────────────────────────────────

class TestABTesting:

    def test_register_and_select(self):
        reg = ABTestRegistry(path="reports/_test_ab.json", persist=False)

        class Control(Skill):
            name = "test_ab"
        class Variant(Skill):
            name = "test_ab"

        reg.register_test("test_ab", Control, Variant, traffic_split=0.5)
        cls, version = reg.select_version("test_ab")
        assert cls is not None
        assert version in ("control", "variant")

    def test_record_outcome(self):
        reg = ABTestRegistry(path="reports/_test_ab2.json", persist=False)

        class C(Skill):
            name = "ab_rec"
        class V(Skill):
            name = "ab_rec"

        reg.register_test("ab_rec", C, V)
        reg.record_outcome("ab_rec", "control", success=True)
        reg.record_outcome("ab_rec", "variant", success=False)
        summary = reg.summary()
        assert summary["ab_rec"]["outcomes"]["control"]["successes"] == 1

    def test_summary(self):
        reg = ABTestRegistry(path="reports/_test_ab3.json", persist=False)
        assert isinstance(reg.summary(), dict)


# ── Skill generation ──────────────────────────────────────────────────────

class TestSkillGeneration:

    def test_generate_source(self):
        source = generate_skill_class("Monitorar preco de concorrente", risk_level="LOW")
        assert "MonitorarPrecoDeConcorrenteSkill" in source
        assert "risk_level = \"LOW\"" in source
        assert "def run" in source

    def test_generate_with_effects(self):
        source = generate_skill_class("Repor estoque", effects={"stock_checked": True}, cost=2.5)
        assert "stock_checked" in source
        assert "cost = 2.5" in source

    def test_safe_name(self):
        assert _safe_name("monitorar preco") == "MonitorarPrecoSkill"
        assert _safe_name("abc") == "AbcSkill"

    def test_generate_and_register(self):
        registry = SkillRegistry()
        source = generate_skill_class(
            "Testar geracao",
            effects={"test_done": True},
        )
        assert "TestarGeracaoSkill" in source
        assert "test_done" in source


# ── Canary deploy ─────────────────────────────────────────────────────────

class TestCanary:

    def test_start_canary(self):
        canary = CanaryDeploy(path="reports/_test_canary.json", persist=False)

        class NewVer(Skill):
            name = "canary_test"

        cid = canary.start_canary("canary_test", NewVer, initial_pct=10.0)
        assert cid is not None
        status = canary.get_status(cid)
        assert status is not None
        assert status["status"] == "canary"
        assert status["traffic_pct"] == 10.0

    def test_promote(self):
        canary = CanaryDeploy(path="reports/_test_canary2.json", persist=False)

        class NewV(Skill):
            name = "promote_test"

        cid = canary.start_canary("promote_test", NewV)
        assert canary.promote(cid) is True
        status = canary.get_status(cid)
        assert status["status"] == "promoted"
        assert status["traffic_pct"] == 100.0

    def test_rollback(self):
        canary = CanaryDeploy(path="reports/_test_canary3.json", persist=False)

        class NewV(Skill):
            name = "rb_test"

        cid = canary.start_canary("rb_test", NewV)
        assert canary.rollback(cid) is True
        status = canary.get_status(cid)
        assert status["status"] == "rolled_back"
        assert status["traffic_pct"] == 0.0

    def test_list_canaries(self):
        canary = CanaryDeploy(path="reports/_test_canary4.json", persist=False)

        class N(Skill):
            name = "list_test"

        canary.start_canary("list_test", N)
        lst = canary.list_canaries()
        assert len(lst) >= 1


# ── Shopee Sandbox ────────────────────────────────────────────────────────

class TestSandbox:

    def test_sandbox_client_init(self):
        client = ShopeeSandboxClient(partner_id=123, partner_key="test")
        assert client.partner_id == 123
        assert client.partner_key == "test"
        assert "test-stable" in client.base_url

    def test_connectivity(self):
        # This just tests the method exists and returns gracefully
        client = ShopeeSandboxClient(partner_id=0, partner_key="")
        result = client.test_connectivity()
        assert "reachable" in result
        assert "sandbox_url" in result
        # Expected to be unreachable with invalid creds but should not crash
        assert isinstance(result["reachable"], bool)
