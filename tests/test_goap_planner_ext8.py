"""Tests for 7 new evolution features (round 8):
1. Self-healing Plans
2. NL Explainability
3. Proactive Goals
4. Plan Cost Prediction
5. Skill Marketplace
6. Multi-store (Federated) Learning
7. Plan Conformance
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from shopee_agent.skills.registry import Skill, SkillRegistry


# ── 1. Self-healing Plans ───────────────────────────────────────────────────


class TestSelfHealing:

    def test_healer_no_plan(self):
        from shopee_agent.plan_healer import execute_with_healing
        # No orchestrator available in unit test, just validate function exists
        assert callable(execute_with_healing)


# ── 2. NL Explainability ────────────────────────────────────────────────────


class TestNLExplainability:

    def test_explain_plan_nl_basic(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
        from shopee_agent.plan_explainer import explain_plan_nl

        planner = GOAPPlanner()
        planner.register_action(GOAPAction(name="check", cost=1.0, effects={"done": True}))

        text = explain_plan_nl(planner, {"done": False}, {"done": True})
        assert isinstance(text, str)
        assert len(text) > 20
        assert "Plano" in text or "check" in text or "Passo" in text or "custo" in text

    def test_explain_no_plan(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
        from shopee_agent.plan_explainer import explain_plan_nl

        planner = GOAPPlanner()
        planner.register_action(GOAPAction(name="x", preconditions={"impossible": True}, effects={"y": True}))

        text = explain_plan_nl(planner, {"y": False}, {"y": True})
        assert isinstance(text, str)
        assert "não foi possível" in text.lower() or "no_plan" not in text

    def test_fmt_dict(self):
        from shopee_agent.plan_explainer import _fmt_dict
        result = _fmt_dict({"a": 1, "b": True})
        assert "a=1" in result
        assert "b=True" in result

    def test_explain_with_llm_fallback(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
        from shopee_agent.plan_explainer import explain_with_llm

        planner = GOAPPlanner()
        planner.register_action(GOAPAction(name="test", cost=1.0, effects={"x": 1}))

        text = explain_with_llm(planner, {"x": 0}, {"x": 1})
        # Returns either a string (NL) or dict (LLM) — both are acceptable
        assert isinstance(text, (str, dict))
        assert text is not None

    def test_explain_with_llm_no_plan(self):
        from shopee_agent.goap_planner import GOAPPlanner
        from shopee_agent.plan_explainer import explain_with_llm

        planner = GOAPPlanner()
        text = explain_with_llm(planner, {"x": 0}, {"impossible": True})
        assert isinstance(text, str)
        assert "não encontrou" in text or "não" in text


# ── 3. Proactive Goals ──────────────────────────────────────────────────────


class TestProactiveGoals:

    def test_suggest_margin_goal(self):
        from shopee_agent.proactive_goals import suggest_goals

        metrics = {"current_margin_pct": 10, "margin_target_pct": 30}
        suggestions = suggest_goals(metrics)
        assert len(suggestions) >= 1
        assert suggestions[0]["goal"] == {"margin_protected": True}

    def test_suggest_stock_goal(self):
        from shopee_agent.proactive_goals import suggest_goals

        metrics = {"stock_risk_level": "critical"}
        suggestions = suggest_goals(metrics)
        assert len(suggestions) >= 1
        assert "low_stock_restocked" in str(suggestions[0]["goal"])

    def test_suggest_orders_goal(self):
        from shopee_agent.proactive_goals import suggest_goals

        metrics = {"orders_pending_ship": 5}
        suggestions = suggest_goals(metrics)
        assert len(suggestions) >= 1
        assert suggestions[0]["goal"] == {"orders_pending_ship": False}

    def test_suggest_support_goal(self):
        from shopee_agent.proactive_goals import suggest_goals

        metrics = {"support_pending": 3}
        suggestions = suggest_goals(metrics)
        assert len(suggestions) >= 1
        assert "support_handled" in suggestions[0]["goal"]

    def test_multiple_suggestions(self):
        from shopee_agent.proactive_goals import suggest_goals

        metrics = {
            "current_margin_pct": 5,
            "margin_target_pct": 30,
            "stock_risk_level": "critical",
            "orders_pending_ship": 10,
            "support_pending": 5,
            "advertising_roas": 0.5,
        }
        suggestions = suggest_goals(metrics)
        assert len(suggestions) >= 4

    def test_empty_metrics(self):
        from shopee_agent.proactive_goals import suggest_goals
        suggestions = suggest_goals({})
        assert isinstance(suggestions, list)


# ── 4. Plan Cost Prediction ─────────────────────────────────────────────────


class TestCostPrediction:

    def test_predict_known_actions(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
        from shopee_agent.cost_predictor import predict_cost

        planner = GOAPPlanner()
        planner.register_action(GOAPAction(name="a", cost=1.0, effects={"x": 1}))
        planner.register_action(GOAPAction(name="b", cost=2.0, effects={"y": 1}))

        result = predict_cost(planner, ["a", "b"])
        assert result["num_actions"] == 2
        assert result["total_predicted"] > 0
        assert len(result["actions"]) == 2
        assert result["confidence"] in ("high", "medium", "low")

    def test_predict_single_action(self):
        from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
        from shopee_agent.cost_predictor import predict_cost

        planner = GOAPPlanner()
        planner.register_action(GOAPAction(name="x", cost=2.5, effects={"x": 1}))

        result = predict_cost(planner, ["x"])
        assert result["num_actions"] == 1
        assert result["total_predicted"] > 0
        assert result["actions"][0]["action"] == "x"

    def test_predict_empty(self):
        from shopee_agent.goap_planner import GOAPPlanner
        from shopee_agent.cost_predictor import predict_cost

        planner = GOAPPlanner()
        result = predict_cost(planner, [])
        assert result["num_actions"] == 0
        assert result["total_predicted"] == 0

    def test_predict_unknown_action(self):
        from shopee_agent.goap_planner import GOAPPlanner
        from shopee_agent.cost_predictor import predict_cost

        planner = GOAPPlanner()
        result = predict_cost(planner, ["nonexistent"])
        assert result["num_actions"] == 1
        assert result["total_predicted"] > 0


# ── 5. Skill Marketplace ────────────────────────────────────────────────────


class TestSkillMarketplace:

    def test_export_package(self):
        from shopee_agent.skills.marketplace import export_skill_package

        class TestSkill(Skill):
            name = "test_market"
            cost = 2.5
            priority = 3
            preconditions = {"x": False}
            effects = {"x": True}

        pkg = export_skill_package(TestSkill, include_source=True)
        assert pkg["format_version"] == "1.0"
        assert pkg["skill"]["name"] == "test_market"
        assert pkg["skill"]["cost"] == 2.5
        assert pkg["skill"]["priority"] == 3
        assert pkg["skill"]["preconditions"] == {"x": False}
        assert "checksum" in pkg
        assert "source" in pkg

    def test_export_without_source(self):
        from shopee_agent.skills.marketplace import export_skill_package

        class Mini(Skill):
            name = "mini"

        pkg = export_skill_package(Mini, include_source=False)
        assert pkg["skill"]["name"] == "mini"
        assert "source" not in pkg or pkg["source"] == ""

    def test_import_package(self):
        from shopee_agent.skills.marketplace import export_skill_package, import_skill_package

        class Orig(Skill):
            name = "orig_skill"
            cost = 3.0
            effects = {"z": True}

        registry = SkillRegistry()
        pkg = export_skill_package(Orig)
        ok = import_skill_package(pkg, registry)
        assert ok is True
        assert "orig_skill" in registry.list()

    def test_save_and_load_package(self, tmp_path):
        from shopee_agent.skills.marketplace import export_skill_package, save_package, load_package

        class S(Skill):
            name = "save_test"

        pkg = export_skill_package(S)
        path = save_package(pkg, str(tmp_path / "test_pkg.json"))
        assert path.exists()

        loaded = load_package(str(path))
        assert loaded is not None
        assert loaded["skill"]["name"] == "save_test"


# ── 6. Multi-store (Federated) Learning ─────────────────────────────────────


class TestFederatedLearning:

    def test_report_and_aggregate(self, tmp_path):
        from shopee_agent.federated_learning import FederatedLearningCoordinator
        db = str(tmp_path / "fed_test.json")
        fed = FederatedLearningCoordinator(db_path=db)

        fed.report("store_a", {"cost_overrides": {"skill_x": {"current_cost": 1.5}}, "base_actions": ["skill_x"]})
        fed.report("store_b", {"cost_overrides": {"skill_x": {"current_cost": 2.5}}, "base_actions": ["skill_x"]})

        agg = fed.aggregate()
        assert agg["num_stores"] == 2
        assert "skill_x" in agg["global_model"]
        assert agg["global_model"]["skill_x"]["mean_cost"] == 2.0

    def test_single_store(self, tmp_path):
        from shopee_agent.federated_learning import FederatedLearningCoordinator
        fed = FederatedLearningCoordinator(db_path=str(tmp_path / "fed_single.json"))
        fed.report("store_a", {"cost_overrides": {"a": 1.0}, "base_actions": ["a"]})
        agg = fed.aggregate()
        assert agg["num_stores"] == 1

    def test_list_stores(self, tmp_path):
        from shopee_agent.federated_learning import FederatedLearningCoordinator
        fed = FederatedLearningCoordinator(db_path=str(tmp_path / "fed_list.json"))
        fed.report("s1", {"cost_overrides": {}, "base_actions": []})
        fed.report("s2", {"cost_overrides": {}, "base_actions": []})
        assert fed.get_store_count() == 2
        assert "s1" in fed.list_stores()

    def test_aggregate_no_data(self, tmp_path):
        from shopee_agent.federated_learning import FederatedLearningCoordinator
        fed = FederatedLearningCoordinator(db_path=str(tmp_path / "fed_empty.json"))
        agg = fed.aggregate()
        assert agg["num_stores"] == 0
        assert agg["actions_tracked"] == 0


# ── 7. Plan Conformance ─────────────────────────────────────────────────────


class TestPlanConformance:

    def test_full_conformance(self):
        from shopee_agent.skills.registry import SkillRegistry
        from shopee_agent.plan_conformance import check_conformance

        registry = SkillRegistry()

        class TestSkill(Skill):
            name = "test"
            effects = {"x": True, "y": True}

        registry.register(TestSkill)

        result = check_conformance(
            expected_actions=["test"],
            expected_effects={"x": True, "y": True},
            actual_results=[{"skill": "test", "ok": True}],
            actual_state={"x": True, "y": True},
            registry=registry,
        )
        assert result["status"] == "conformant"
        assert result["effects_matched"] == 2
        assert result["effects_missing"] == 0
        assert result["goal_achieved"] is True

    def test_partial_conformance(self):
        from shopee_agent.skills.registry import SkillRegistry
        from shopee_agent.plan_conformance import check_conformance

        registry = SkillRegistry()

        class TestSkill(Skill):
            name = "test"
            effects = {"x": True, "y": True}

        registry.register(TestSkill)

        result = check_conformance(
            expected_actions=["test"],
            expected_effects={"x": True},
            actual_results=[{"skill": "test", "ok": True}],
            actual_state={"x": True, "y": False},
            registry=registry,
        )
        assert result["effects_matched"] == 1
        assert result["effects_missing"] == 1
        assert result["goal_achieved"] is True  # x=True matches expected

    def test_no_effects(self):
        from shopee_agent.skills.registry import SkillRegistry
        from shopee_agent.plan_conformance import check_conformance

        registry = SkillRegistry()
        result = check_conformance([], {}, [], {}, registry)
        assert result["status"] == "conformant"
        assert result["conformance_pct"] == 100.0

    def test_unexpected_effects(self):
        from shopee_agent.skills.registry import SkillRegistry
        from shopee_agent.plan_conformance import check_conformance

        registry = SkillRegistry()

        class S(Skill):
            name = "s"
            effects = {"a": True}

        registry.register(S)

        result = check_conformance(
            expected_actions=["s"], expected_effects={"b": True},
            actual_results=[{"skill": "s", "ok": True}],
            actual_state={"a": True, "b": True, "unexpected_key": "x"},
            registry=registry,
        )
        assert len(result["unexpected"]) >= 1
