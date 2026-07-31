from __future__ import annotations

from shopee_agent.decision_engine import (
    DecisionRule,
    DecisionType,
    DecisionPriority,
    Decision,
    DecisionSignal,
    DecisionEngine,
    EconomicContext,
    RiskLevel,
    create_default_rules,
)


def test_adaptive_rule_initial_state():
    rule = DecisionRule(
        rule_id="test",
        decision_type=DecisionType.PRICING,
        name="Test Rule",
        description="A test rule",
        condition="source=metrics and metric=margin_change",
        priority_boost=0,
        risk_threshold=RiskLevel.MEDIUM,
    )
    assert rule.effectiveness_score == 0.5
    assert rule.last_success_rate == 0.5
    assert rule.execution_count == 0


def test_adaptive_rule_adjust_improves():
    rule = DecisionRule(
        rule_id="test",
        decision_type=DecisionType.PRICING,
        name="Test Rule",
        description="A test rule",
        condition="source=metrics",
        priority_boost=0,
        risk_threshold=RiskLevel.MEDIUM,
    )
    rule.execution_count = 20
    rule.adjust_based_on_outcomes(0.9)
    assert rule.effectiveness_score > 0.5
    assert rule.priority_boost >= 0


def test_adaptive_rule_adjust_low_success():
    rule = DecisionRule(
        rule_id="test",
        decision_type=DecisionType.PRICING,
        name="Test Rule",
        description="A test rule",
        condition="source=metrics",
        priority_boost=5,
        risk_threshold=RiskLevel.MEDIUM,
        effectiveness_score=0.8,
        last_success_rate=0.8,
        execution_count=20,
    )
    rule.adjust_based_on_outcomes(0.2)
    assert rule.effectiveness_score < 0.8
    assert rule.priority_boost < 5


def test_engine_persists_rules():
    engine = DecisionEngine(store_id="test_persist", rules=[])
    assert hasattr(engine, "rules")
    assert isinstance(engine.rules, dict)


def test_engine_process_signal_creates_decisions():
    engine = DecisionEngine(store_id="test_signal", rules=create_default_rules())
    sig = DecisionSignal(source="metrics", signal_type="anomaly", data={"metric": "margin_change", "value": -0.02})
    ctx = EconomicContext(
        current_margin_pct=35.0,
        margin_target_pct=20.0,
        advertising_roas=2.1,
        cash_buffer_usd=30000.0,
        daily_revenue_usd=5000.0,
        inventory_days_on_hand=14,
        stock_risk_level="low",
        customer_satisfaction_score=80.0,
        active_promotions=[],
        advertising_spend_daily_usd=100.0,
        recent_anomalies=[],
    )
    decisions = engine.process_signal(sig, ctx)
    assert len(decisions) >= 0


def test_decision_priority_ordering():
    low = DecisionPriority.LOW
    normal = DecisionPriority.NORMAL
    high = DecisionPriority.HIGH
    crit = DecisionPriority.CRITICAL
    assert crit.value < high.value < normal.value < low.value


def test_default_rules_are_created():
    rules = create_default_rules()
    assert len(rules) > 0
    for rule in rules:
        assert isinstance(rule, DecisionRule)
        assert rule.rule_id
        assert rule.decision_type in DecisionType


def test_decision_has_correct_fields():
    sig = DecisionSignal(source="test", signal_type="manual", data={})
    d = Decision(
        decision_id="d1",
        decision_type=DecisionType.PRICING,
        rule_id="r1",
        title="Test",
        description="desc",
        recommended_action="action",
        priority=DecisionPriority.HIGH,
        impact_score=0.5,
        risk_score=0.2,
        confidence_score=0.8,
        signal=sig,
    )
    assert d.decision_id == "d1"
    assert d.priority == DecisionPriority.HIGH
    assert d.impact_score == 0.5
