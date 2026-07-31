"""
Tests for Decision Engine v1

Tests cover:
- Signal processing
- Rule matching
- Decision generation
- Guardrail evaluation
- Audit logging
"""

import pytest
import json
from pathlib import Path
import tempfile

from shopee_agent.decision_engine import (
    DecisionEngine,
    DecisionSignal,
    DecisionRule,
    EconomicContext,
    DecisionType,
    DecisionPriority,
    DecisionStatus,
    create_default_rules,
)


@pytest.fixture
def temp_log_path():
    """Create temporary log file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def engine(temp_log_path):
    """Create DecisionEngine instance with default rules."""
    rules = create_default_rules()
    eng = DecisionEngine("test_store", rules=rules, log_path=temp_log_path)
    eng.pending_decisions.clear()
    eng._save_pending()
    return eng


@pytest.fixture
def normal_context():
    """Create normal economic context."""
    return EconomicContext(
        current_margin_pct=15.0,
        margin_target_pct=18.0,
        daily_revenue_usd=5000.0,
        cash_buffer_usd=50000.0,
        inventory_days_on_hand=15,
        stock_risk_level="normal",
        active_promotions=2,
        advertising_spend_daily_usd=500.0,
        advertising_roas=2.5,
        customer_satisfaction_score=85.0,
        recent_anomalies=[],
    )


@pytest.fixture
def crisis_context():
    """Create crisis economic context (to test guardrails)."""
    return EconomicContext(
        current_margin_pct=8.0,
        margin_target_pct=18.0,
        daily_revenue_usd=2000.0,
        cash_buffer_usd=500.0,
        inventory_days_on_hand=2,
        stock_risk_level="critical",
        active_promotions=5,
        advertising_spend_daily_usd=1000.0,
        advertising_roas=0.8,
        customer_satisfaction_score=60.0,
        recent_anomalies=["high_return_rate", "payment_failures"],
    )


class TestDecisionEngine:
    """Test core Decision Engine functionality."""
    
    def test_engine_initialization(self, engine):
        """Test engine starts with rules loaded."""
        summary = engine.summary()
        assert summary["store_id"] == "test_store"
        assert summary["total_rules"] == 3
        assert summary["pending_decisions"] == 0
    
    def test_add_rule(self, engine):
        """Test adding a new rule at runtime."""
        new_rule = DecisionRule(
            rule_id="test_custom",
            decision_type=DecisionType.CUSTOMER_SERVICE,
            name="Test Rule",
            description="Test",
            condition="test_condition",
        )
        engine.add_rule(new_rule)
        assert "test_custom" in engine.rules
        assert len(engine.rules) == 4


class TestSignalProcessing:
    """Test signal processing and rule matching."""
    
    def test_process_pricing_signal(self, engine, normal_context):
        """Test processing a pricing signal."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"metric": "margin_drop", "severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        # Should match pricing rule
        assert len(decisions) > 0
        assert any(d.decision_type == DecisionType.PRICING for d in decisions)
    
    def test_process_ads_signal(self, engine, normal_context):
        """Test processing an ads signal."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="opportunity",
            data={"metric": "low_roas_campaign", "severity": 0.5},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        # Should match ads rule
        assert any(d.decision_type == DecisionType.ADS for d in decisions)
    
    def test_process_inventory_signal(self, engine, normal_context):
        """Test processing an inventory signal."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="risk",
            data={"metric": "low_stock", "severity": 0.8},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        # Should match inventory rule
        assert any(d.decision_type == DecisionType.INVENTORY for d in decisions)


class TestGuardrails:
    """Test guardrail evaluation."""
    
    def test_guardrails_pass_in_normal_context(self, engine, normal_context):
        """Test that decisions pass guardrails in healthy context."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        # At least one decision should be approved
        approved = [d for d in decisions if d.status == DecisionStatus.APPROVED]
        assert len(approved) > 0
        
        # Approved decisions should pass all guardrails
        for decision in approved:
            assert all(decision.guardrails_passed.values())
    
    def test_guardrails_reject_in_crisis(self, engine, crisis_context):
        """Test that risky decisions are rejected in crisis."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, crisis_context)
        
        # Many decisions should be rejected in crisis
        rejected = [d for d in decisions if d.status == DecisionStatus.REJECTED]
        assert len(rejected) > 0
        
        # Check which guardrails failed
        for decision in rejected:
            failed_guards = [k for k, v in decision.guardrails_passed.items() if not v]
            assert len(failed_guards) > 0
    
    def test_margin_floor_guardrail(self, engine):
        """Test margin floor guardrail enforcement."""
        weak_margin_context = EconomicContext(
            current_margin_pct=13.0,  # Below 80% of target (18 * 0.8 = 14.4)
            margin_target_pct=18.0,
            daily_revenue_usd=5000.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=15,
            stock_risk_level="normal",
            active_promotions=2,
            advertising_spend_daily_usd=500.0,
            advertising_roas=2.5,
            customer_satisfaction_score=85.0,
            recent_anomalies=[],
        )
        
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, weak_margin_context)
        
        for decision in decisions:
            assert not decision.guardrails_passed.get("margin_floor", False)


class TestDecisionScoring:
    """Test decision scoring and priority calculation."""
    
    def test_decision_has_scores(self, engine, normal_context):
        """Test that generated decisions have proper scores."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        for decision in decisions:
            assert -1.0 <= decision.impact_score <= 1.0
            assert 0.0 <= decision.risk_score <= 1.0
            assert 0.0 <= decision.confidence_score <= 1.0
            assert decision.priority in DecisionPriority
    
    def test_priority_escalation_in_crisis(self, engine, crisis_context):
        """Test that priority escalates during crisis."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, crisis_context)
        
        # In crisis, priorities should be higher (lower enum values)
        avg_priority_value = sum(d.priority.value for d in decisions) / len(decisions) if decisions else 0
        assert avg_priority_value <= 2.0  # Average should be HIGH or CRITICAL


class TestAuditLogging:
    """Test decision audit trail."""
    
    def test_decisions_logged(self, engine, normal_context, temp_log_path):
        """Test that decisions are written to audit log."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        _decisions = engine.process_signal(signal, normal_context)
        
        # Read log file
        with open(temp_log_path) as f:
            logged_lines = f.readlines()
        
        assert len(logged_lines) > 0
        
        # Verify logged decisions are valid JSON
        for line in logged_lines:
            logged_decision = json.loads(line)
            assert "decision_id" in logged_decision
            assert "status" in logged_decision
    
    def test_decision_execution_logged(self, engine, normal_context, temp_log_path):
        """Test that decision execution is logged."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        approved = [d for d in decisions if d.status == DecisionStatus.APPROVED]
        
        if approved:
            first_decision = approved[0]
            engine.execute_decision(first_decision.decision_id)
            
            # Check log
            with open(temp_log_path) as f:
                logged_lines = f.readlines()
            
            # Should have decision creation + execution logs
            assert len(logged_lines) >= 2


class TestDecisionRetrieval:
    """Test querying pending decisions."""
    
    def test_get_pending_decisions(self, engine, normal_context):
        """Test retrieving all pending decisions."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        engine.process_signal(signal, normal_context)
        
        pending = engine.get_pending_decisions()
        assert len(pending) > 0
    
    def test_filter_by_type(self, engine, normal_context):
        """Test filtering decisions by type."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        engine.process_signal(signal, normal_context)
        
        pricing_decisions = engine.get_pending_decisions(decision_type=DecisionType.PRICING)
        assert all(d.decision_type == DecisionType.PRICING for d in pricing_decisions)
    
    def test_filter_by_priority(self, engine, normal_context):
        """Test filtering decisions by minimum priority."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        engine.process_signal(signal, normal_context)
        
        high_priority = engine.get_pending_decisions(min_priority=DecisionPriority.HIGH)
        assert all(d.priority.value <= DecisionPriority.HIGH.value for d in high_priority)


class TestDecisionModel:
    """Test data model integrity."""
    
    def test_decision_serialization(self, engine, normal_context):
        """Test that decisions can be serialized to JSON."""
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        for decision in decisions:
            data = decision.to_dict()
            
            # Verify structure
            assert "decision_id" in data
            assert "decision_type" in data
            assert "priority" in data
            assert "status" in data
            assert "signal" in data
            
            # Verify serializable
            json_str = json.dumps(data)
            assert json_str is not None
    
    def test_signal_context_preserved(self, engine, normal_context):
        """Test that signal context is preserved in decision."""
        context_info = {"campaign_id": 12345, "reason": "custom_test"}
        signal = DecisionSignal(
            source="metrics",
            signal_type="anomaly",
            data={"severity": 0.7},
            context=context_info,
        )
        
        decisions = engine.process_signal(signal, normal_context)
        
        for decision in decisions:
            assert decision.signal.context == context_info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
