"""E2E: Learning system -> memory -> decision feedback loop."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.decision_memory import MemoryLayer, DecisionOutcome
from shopee_agent.learning_system import LearningSystem, LearningReport
from shopee_agent.cognitive_memory import LongTermMemory, MemoryNote
from shopee_agent.decision_adaptive import (
    AdaptiveRule,
    AdaptiveRuleEngine,
    FeedbackLoop,
    AdaptiveIntegrator,
)


@pytest.mark.integration
class TestSkillLearningFromOutcomes:
    """E2E: Learning system evaluates outcomes and produces reports."""

    def test_learning_system_evaluates_outcomes(self, tmp_path):
        outcomes_path = tmp_path / "outcomes.jsonl"
        notes_path = tmp_path / "notes.jsonl"
        mem = LongTermMemory(
            outcomes_path=str(outcomes_path),
            notes_path=str(notes_path),
        )
        mem.remember_outcome(DecisionOutcome(
            decision_id="d1", rule_id="pricing_rule",
            outcome_type="success", impact_realized=0.15,
            executed_at=datetime.now(timezone.utc),
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="d2", rule_id="pricing_rule",
            outcome_type="success", impact_realized=0.10,
            executed_at=datetime.now(timezone.utc),
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="d3", rule_id="stock_rule",
            outcome_type="failure", impact_realized=-0.05,
            executed_at=datetime.now(timezone.utc),
        ))
        learning = LearningSystem(memory=mem)
        report = learning.evaluate(window_days=30, persist_note=False)
        assert isinstance(report, LearningReport)
        assert report.total_outcomes == 3
        assert report.success_rate > 0.5
        assert report.failure_rate > 0
        assert len(report.signals) == 3
        signal_names = {s.name for s in report.signals}
        assert "success_rate" in signal_names
        assert "failure_rate" in signal_names
        assert "partial_rate" in signal_names

    def test_learning_report_contains_insights_and_recommendations(self, tmp_path):
        mem = LongTermMemory(
            outcomes_path=str(tmp_path / "out.jsonl"),
            notes_path=str(tmp_path / "notes.jsonl"),
        )
        for i in range(10):
            mem.remember_outcome(DecisionOutcome(
                decision_id=f"d{i}", rule_id="test_rule",
                outcome_type="success" if i < 7 else "failure",
                impact_realized=0.1,
                executed_at=datetime.now(timezone.utc),
            ))
        learning = LearningSystem(memory=mem)
        report = learning.evaluate(window_days=30, persist_note=False)
        assert len(report.insights) >= 0
        assert len(report.recommendations) >= 1

    def test_weekly_report_generates_shorter_window(self, tmp_path):
        mem = LongTermMemory(
            outcomes_path=str(tmp_path / "out.jsonl"),
            notes_path=str(tmp_path / "notes.jsonl"),
        )
        for i in range(5):
            mem.remember_outcome(DecisionOutcome(
                decision_id=f"d{i}", rule_id="weekly_rule",
                outcome_type="success",
                executed_at=datetime.now(timezone.utc),
            ))
        learning = LearningSystem(memory=mem)
        report = learning.weekly_report(persist_note=False)
        assert report.window_days == 7

    def test_record_feedback_stores_note(self, tmp_path):
        mem = LongTermMemory(
            outcomes_path=str(tmp_path / "out.jsonl"),
            notes_path=str(tmp_path / "notes.jsonl"),
        )
        learning = LearningSystem(memory=mem)
        result = learning.record_feedback(
            title="Test feedback",
            summary="User provided positive feedback",
            kind="feedback",
            metadata={"source": "user"},
        )
        assert result["kind"] == "feedback"
        assert result["title"] == "Test feedback"

    def test_search_lessons_returns_matches(self, tmp_path):
        mem = LongTermMemory(
            outcomes_path=str(tmp_path / "out.jsonl"),
            notes_path=str(tmp_path / "notes.jsonl"),
        )
        learning = LearningSystem(memory=mem)
        learning.record_feedback(
            title="Margin drop detected",
            summary="Margin dropped below 15% due to competitor pricing",
            kind="feedback",
            metadata={"metric": "margin"},
        )
        results = learning.search_lessons("margin drop", limit=5)
        assert len(results) > 0
        assert any("margin" in str(r) for r in results)


@pytest.mark.integration
class TestMemoryStorageAndRetrieval:
    """E2E: Memory layer stores, retrieves, and analyzes outcomes."""

    def test_memory_layer_persists_outcome_to_jsonl(self, tmp_path):
        outcomes_file = tmp_path / "test_outcomes.jsonl"
        mem = MemoryLayer(path=str(outcomes_file))
        outcome = DecisionOutcome(
            decision_id="mem_test_1",
            rule_id="memory_rule",
            outcome_type="success",
            impact_realized=0.2,
        )
        mem.remember_outcome(outcome)
        lines = outcomes_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        saved = json.loads(lines[0])
        assert saved["decision_id"] == "mem_test_1"

    def test_memory_retrieves_recent_outcomes(self, tmp_path):
        mem = MemoryLayer(path=str(tmp_path / "out.jsonl"))
        for i in range(5):
            mem.remember_outcome(DecisionOutcome(
                decision_id=f"retrieve_{i}", rule_id="r1",
                outcome_type="success",
            ))
        outcomes = mem.list_outcomes(limit=10)
        assert len(outcomes) == 5

    def test_rule_effectiveness_calculation(self, tmp_path):
        mem = MemoryLayer(path=str(tmp_path / "eff.jsonl"))
        mem.remember_outcome(DecisionOutcome(
            decision_id="e1", rule_id="eff_rule", outcome_type="success",
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="e2", rule_id="eff_rule", outcome_type="failure",
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="e3", rule_id="eff_rule", outcome_type="partial",
        ))
        eff = mem.get_rule_effectiveness("eff_rule")
        assert eff == 0.5, f"Expected 0.5 (1 success + 0.5 partial) / 3, got {eff}"

    def test_predicted_outcome_for_rule(self, tmp_path):
        mem = MemoryLayer(path=str(tmp_path / "pred.jsonl"))
        mem.remember_outcome(DecisionOutcome(
            decision_id="p1", rule_id="pred_rule",
            outcome_type="success", impact_realized=0.15,
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="p2", rule_id="pred_rule",
            outcome_type="success", impact_realized=0.25,
        ))
        pred = mem.predict_outcome_for_rule("pred_rule")
        assert pred == 0.20

    def test_rank_similar_decisions(self, tmp_path):
        mem = MemoryLayer(path=str(tmp_path / "rank.jsonl"))
        mem.remember_outcome(DecisionOutcome(
            decision_id="s1", rule_id="rank_rule",
            outcome_type="success", metadata={"metric": "margin_drop"},
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="s2", rule_id="other_rule",
            outcome_type="success", metadata={"metric": "sales_drop"},
        ))
        results = mem.rank_similar_decisions({"metric": "margin_drop", "rule_id": "rank_rule"})
        assert len(results) >= 1
        assert results[0].rule_id == "rank_rule"


@pytest.mark.integration
class TestDecisionFeedbackIntegration:
    """E2E: Decision outcomes feed back into adaptive rules."""

    def test_adaptive_rule_records_outcome_and_adjusts_weight(self, tmp_path):
        rules_path = tmp_path / "rules_state.json"
        engine = AdaptiveRuleEngine(rules_path=str(rules_path))
        rule = AdaptiveRule(
            rule_id="adapt_weight",
            condition='margin_pct < 18',
            action='{"action": "protect_margin"}',
            weight=1.0,
        )
        engine.add_rule(rule)
        engine.record_outcome("adapt_weight", success=True, impact=0.1)
        engine.record_outcome("adapt_weight", success=True, impact=0.05)
        engine.record_outcome("adapt_weight", success=False, impact=-0.02)
        stats = engine.get_stats()
        assert stats["total_rules"] == 1
        assert stats["total_successes"] >= 2
        assert stats["total_failures"] >= 1

    def test_feedback_loop_processes_outcomes(self, tmp_path):
        memory = MemoryLayer(path=str(tmp_path / "fb_outcomes.jsonl"))
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "fb_rules.json"))
        loop = FeedbackLoop(engine=engine, memory=memory)
        rule = AdaptiveRule(
            rule_id="fb_rule",
            condition='daily_revenue > 1000',
            action='{"action": "increase_ad_spend"}',
        )
        engine.add_rule(rule)
        memory.remember_outcome(DecisionOutcome(
            decision_id="fb1", rule_id="fb_rule",
            outcome_type="success", impact_realized=0.2,
        ))
        memory.remember_outcome(DecisionOutcome(
            decision_id="fb2", rule_id="fb_rule",
            outcome_type="success", impact_realized=0.15,
        ))
        memory.remember_outcome(DecisionOutcome(
            decision_id="fb3", rule_id="fb_rule",
            outcome_type="failure", impact_realized=-0.05,
        ))
        result = loop.run_adaptation_cycle()
        assert result["cycle"] >= 1
        assert result["outcomes_analyzed"] >= 3
        assert "engine_stats" in result

    def test_adaptive_rule_evaluation(self, tmp_path):
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "eval_rules.json"))
        engine.add_rule(AdaptiveRule(
            rule_id="eval_test",
            condition='margin_pct < 18',
            action='{"action": "flag_review"}',
            weight=1.0,
        ))
        results = engine.evaluate({"margin_pct": 15.0, "daily_revenue": 5000})
        assert len(results) == 1
        assert results[0]["rule_id"] == "eval_test"
        assert results[0]["result"]["action"] == "flag_review"

    def test_adaptive_rule_skipped_when_condition_false(self, tmp_path):
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "skip_rules.json"))
        engine.add_rule(AdaptiveRule(
            rule_id="skip_test",
            condition='margin_pct < 10',
            action='{"action": "urgent_review"}',
        ))
        results = engine.evaluate({"margin_pct": 15.0})
        assert len(results) == 0


@pytest.mark.integration
class TestAdaptiveRulesUpdate:
    """E2E: Adaptive rules are created, updated, and pruned."""

    def test_add_and_remove_rule(self, tmp_path):
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "add_remove.json"))
        rule = AdaptiveRule(rule_id="temp_rule", condition="True", action="{}")
        assert engine.add_rule(rule) is True
        assert engine.count() == 1
        assert engine.remove_rule("temp_rule") is True
        assert engine.count() == 0

    def test_suggest_new_rules_from_patterns(self, tmp_path):
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "suggest.json"))
        patterns = [
            {"condition": "cash_buffer > 5000", "action": '{"action": "invest"}', "name": "invest_pattern", "initial_weight": 0.6},
        ]
        suggestions = engine.suggest_new_rules(patterns)
        assert len(suggestions) == 1
        assert suggestions[0].condition == "cash_buffer > 5000"
        assert suggestions[0].weight == 0.6

    def test_prune_low_performers(self, tmp_path):
        memory = MemoryLayer(path=str(tmp_path / "prune_outcomes.jsonl"))
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "prune_rules.json"))
        loop = FeedbackLoop(engine=engine, memory=memory)
        engine.add_rule(AdaptiveRule(
            rule_id="good_rule",
            condition="True", action="{}",
            weight=1.0, success_count=10, failure_count=1,
        ))
        engine.add_rule(AdaptiveRule(
            rule_id="bad_rule",
            condition="True", action="{}",
            weight=0.01, success_count=1, failure_count=10,
        ))
        result = loop.run_adaptation_cycle()
        assert "pruned_rules" in result

    def test_weight_adjustment_boost_successful_rules(self, tmp_path):
        engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "weight_adj.json"))
        engine.add_rule(AdaptiveRule(
            rule_id="boost_me",
            condition="True", action="{}",
            weight=1.0, success_count=10, failure_count=1,
        ))
        engine.add_rule(AdaptiveRule(
            rule_id="penalize_me",
            condition="True", action="{}",
            weight=1.0, success_count=1, failure_count=10,
        ))
        engine.adjust_weights()
        boosted = engine._rules["boost_me"]
        penalized = engine._rules["penalize_me"]
        assert boosted.weight > 1.0, "High-success rule should be boosted"
        assert penalized.weight < 1.0, "Low-success rule should be penalized"

    def test_adaptive_integrator_cycle(self, tmp_path):
        from shopee_agent.decision_engine import DecisionEngine
        from shopee_agent.decision_integration import DecisionIntegrator
        from shopee_agent.decision_engine import EconomicContext

        memory = MemoryLayer(path=str(tmp_path / "ai_outcomes.jsonl"))
        engine = DecisionEngine(store_id="test", rules=[])
        integrator = DecisionIntegrator(engine=engine, store_id="test", metrics_dir=str(tmp_path))
        integrator.collect_signals_from_metrics = MagicMock(return_value=[])
        integrator.build_economic_context = MagicMock(return_value=EconomicContext(
            current_margin_pct=15.0, margin_target_pct=18.0,
            daily_revenue_usd=5000, cash_buffer_usd=50000,
            inventory_days_on_hand=15, stock_risk_level="normal",
            active_promotions=0, advertising_spend_daily_usd=500,
            advertising_roas=2.0, customer_satisfaction_score=80,
            recent_anomalies=[],
        ))
        adaptive_engine = AdaptiveRuleEngine(rules_path=str(tmp_path / "ai_rules.json"))
        adaptive_engine.add_rule(AdaptiveRule(
            rule_id="ai_test", condition="margin_pct < 18",
            action='{"action": "protect_margin"}',
        ))
        ai = AdaptiveIntegrator(
            integrator=integrator,
            adaptive_engine=adaptive_engine,
            memory=memory,
            auto_add_suggestions=False,
        )
        result = ai.process_cycle()
        assert "adaptive" in result
        assert result["adaptive"]["rules_total"] >= 1
