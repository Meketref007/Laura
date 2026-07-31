from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from shopee_agent.decision_adaptive import (
    AdaptiveRule,
    AdaptiveRuleEngine,
    FeedbackLoop,
    AdaptiveIntegrator,
)
from shopee_agent.decision_memory import DecisionOutcome, MemoryLayer
from shopee_agent.decision_engine import DecisionEngine, Decision, DecisionStatus


@pytest.fixture
def rule():
    return AdaptiveRule(
        rule_id="r1",
        condition="margin_pct > 15",
        action='{"action": "cut_price", "amount": 5}',
        weight=1.0,
    )


@pytest.fixture
def engine(tmp_path):
    return AdaptiveRuleEngine(rules_path=str(tmp_path / "rules_state.json"))


class TestAdaptiveRuleEngine:
    def test_add_rule(self, engine, rule):
        assert engine.add_rule(rule) is True
        assert engine.count() == 1

    def test_add_rule_duplicate(self, engine, rule):
        engine.add_rule(rule)
        assert engine.add_rule(rule) is False
        assert engine.count() == 1

    def test_remove_rule(self, engine, rule):
        engine.add_rule(rule)
        assert engine.remove_rule("r1") is True
        assert engine.count() == 0

    def test_remove_rule_not_found(self, engine):
        assert engine.remove_rule("nonexistent") is False

    def test_evaluate_rules(self, engine, rule):
        engine.add_rule(rule)
        results = engine.evaluate({"margin_pct": 20})
        assert len(results) == 1
        assert results[0]["rule_id"] == "r1"
        assert results[0]["result"] == {"action": "cut_price", "amount": 5}

    def test_evaluate_rules_no_match(self, engine, rule):
        engine.add_rule(rule)
        results = engine.evaluate({"margin_pct": 10})
        assert results == []

    def test_evaluate_rules_low_weight(self, engine, rule):
        rule.weight = 0.001
        engine.add_rule(rule)
        results = engine.evaluate({"margin_pct": 20})
        assert results == []

    def test_record_outcome_success(self, engine, rule):
        engine.add_rule(rule)
        engine.record_outcome("r1", success=True, impact=0.1)
        assert engine._rules["r1"].success_count == 1
        assert engine._rules["r1"].last_outcome == "success"
        assert engine._rules["r1"].weight == 1.1

    def test_record_outcome_failure(self, engine, rule):
        engine.add_rule(rule)
        engine.record_outcome("r1", success=False, impact=-0.15)
        assert engine._rules["r1"].failure_count == 1
        assert engine._rules["r1"].weight == 0.85

    def test_record_outcome_nonexistent_rule(self, engine):
        engine.record_outcome("missing", success=True)
        assert engine.count() == 0

    def test_adjust_weights(self, engine, rule):
        rule.success_count = 10
        rule.failure_count = 1
        engine.add_rule(rule)
        engine.adjust_weights()
        assert engine._rules["r1"].weight > 1.0

    def test_adjust_weights_low_performer(self, engine, rule):
        rule.rule_id = "r2"
        rule.success_count = 1
        rule.failure_count = 10
        engine.add_rule(rule)
        engine.adjust_weights()
        assert engine._rules["r2"].weight < 1.0

    def test_adjust_weights_insufficient_data(self, engine, rule):
        rule.success_count = 1
        rule.failure_count = 0
        engine.add_rule(rule)
        engine.adjust_weights()
        assert engine._rules["r1"].weight == 1.0

    def test_get_stats_empty(self, engine):
        stats = engine.get_stats()
        assert stats["total_rules"] == 0

    def test_get_stats(self, engine, rule):
        engine.add_rule(rule)
        stats = engine.get_stats()
        assert stats["total_rules"] == 1
        assert stats["active_rules"] == 1

    def test_suggest_new_rules(self, engine):
        patterns = [
            {"condition": "revenue > 1000", "action": '{"action": "invest"}', "name": "grow", "initial_weight": 0.5},
        ]
        suggestions = engine.suggest_new_rules(patterns)
        assert len(suggestions) == 1
        assert suggestions[0].condition == patterns[0]["condition"]

    def test_suggest_new_rules_skips_duplicates(self, engine, rule):
        engine.add_rule(rule)
        patterns = [
            {"condition": "margin_pct > 15", "action": '{"action": "x"}', "name": "dup"},
        ]
        assert engine.suggest_new_rules(patterns) == []

    def test_suggest_new_rules_skips_empty(self, engine):
        assert engine.suggest_new_rules([{"condition": "", "action": ""}]) == []


class TestFeedbackLoop:
    @pytest.fixture
    def memory(self):
        m = MagicMock(spec=MemoryLayer)
        m.list_outcomes.return_value = []
        return m

    @pytest.fixture
    def feedback(self, engine, memory):
        return FeedbackLoop(engine=engine, memory=memory)

    def test_process_outcome(self, feedback, engine, rule):
        engine.add_rule(rule)
        feedback.process_outcome("r1", {"rule_id": "r1", "success": True, "impact": 0.05})
        assert engine._rules["r1"].success_count == 1

    def test_process_outcome_no_rule_id(self, feedback):
        feedback.process_outcome("d1", {"success": True})
        assert True

    @patch("shopee_agent.decision_adaptive.Path.exists", return_value=False)
    @patch("shopee_agent.decision_adaptive.Path.mkdir")
    def test_feedback_loop_process_outcome(self, mock_mkdir, mock_exists, feedback, engine, rule):
        engine.add_rule(rule)
        feedback.process_outcome("r1", {"rule_id": "r1", "success": True, "impact": 0.2})
        assert engine._rules["r1"].success_count == 1
        assert engine._rules["r1"].last_outcome == "success"


class TestAdaptiveIntegrator:
    @pytest.fixture
    def mock_integrator(self):
        integrator = MagicMock()
        integrator.process_cycle.return_value = {"decisions": []}
        engine = MagicMock(spec=DecisionEngine)
        type(engine).pending_decisions = PropertyMock(return_value={})
        integrator.engine = engine
        integrator.build_economic_context.return_value = MagicMock(
            current_margin_pct=20,
            margin_target_pct=25,
            daily_revenue_usd=1000,
            cash_buffer_usd=10000,
            stock_risk_level="normal",
            active_promotions=2,
            advertising_spend_daily_usd=100,
            advertising_roas=3.0,
            customer_satisfaction_score=4.5,
            recent_anomalies=[],
        )
        return integrator

    @pytest.fixture
    def memory(self):
        m = MagicMock(spec=MemoryLayer)
        m.list_outcomes.return_value = []
        return m

    @pytest.fixture
    def adaptive_integrator(self, mock_integrator, engine, memory):
        return AdaptiveIntegrator(
            integrator=mock_integrator,
            adaptive_engine=engine,
            memory=memory,
            auto_add_suggestions=False,
        )

    def test_adaptive_integrator_process_cycle(self, adaptive_integrator, engine, rule):
        engine.add_rule(rule)
        result = adaptive_integrator.process_cycle()
        assert "adaptive" in result
        assert result["adaptive"]["rules_total"] >= 1

    def test_adaptive_integrator_summary(self, adaptive_integrator):
        summary = adaptive_integrator.get_adaptive_summary()
        assert "adaptive_rules" in summary
        assert "cycle_count" in summary
