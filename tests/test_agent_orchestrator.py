"""Tests for Phase 37 multi-agent orchestration."""

from __future__ import annotations

from shopee_agent.agent_orchestrator import AgentOrchestrator
from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator


class DummyEngine:
    def process_signal(self, signal, context):
        return []


class TestAgentOrchestrator:
    def test_conflict_resolution_prefers_margin_protection(self):
        orchestrator = AgentOrchestrator()
        context = EconomicContext(
            current_margin_pct=12.0,
            margin_target_pct=18.0,
            daily_revenue_usd=3200.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=4,
            stock_risk_level="high",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=1.2,
            customer_satisfaction_score=82.0,
            recent_anomalies=["margin_drop"],
        )

        plan = orchestrator.coordinate_cycle_sync(context)

        targets = {action.target for action in plan.approved_actions}
        directions = {action.target: action.direction for action in plan.approved_actions}

        assert "pricing" in targets
        assert directions["pricing"] == "up"
        assert "ads_budget" in targets
        assert directions["ads_budget"] == "down"
        assert "inventory" in targets
        assert directions["inventory"] == "up"
        assert plan.conflicts
        assert any(action.direction == "down" for action in plan.rejected_actions if action.target == "pricing")
        assert plan.consensus_score > 0

    def test_multi_agent_roster_includes_phase_5_agents(self):
        orchestrator = AgentOrchestrator()
        context = EconomicContext(
            current_margin_pct=17.0,
            margin_target_pct=18.0,
            daily_revenue_usd=6200.0,
            cash_buffer_usd=12000.0,
            inventory_days_on_hand=9,
            stock_risk_level="normal",
            active_promotions=1,
            advertising_spend_daily_usd=800.0,
            advertising_roas=2.3,
            customer_satisfaction_score=84.0,
            recent_anomalies=["competitor_price_drop"],
        )

        plan = orchestrator.coordinate_cycle_sync(context)

        all_agents = {action.agent_name for action in plan.approved_actions + plan.rejected_actions}
        approved_agents = {action.agent_name for action in plan.approved_actions}
        rejected_agents = {action.agent_name for action in plan.rejected_actions}

        assert "growth_agent" in all_agents
        assert "finance_agent" in approved_agents
        assert "competitor_agent" in rejected_agents
        assert any(action.target == "pricing" for action in plan.rejected_actions)
        assert any(action.target == "opex" and action.direction == "down" for action in plan.approved_actions)
        assert any(action.target == "ads_budget" and action.direction == "up" for action in plan.approved_actions)
        assert plan.conflicts


class TestDecisionIntegratorOrchestration:
    def test_process_cycle_includes_orchestration_plan(self, tmp_path, monkeypatch):
        engine = DummyEngine()
        orchestrator = AgentOrchestrator()
        integrator = DecisionIntegrator(
            engine=engine,
            store_id="test_store",
            metrics_dir=str(tmp_path),
            agent_orchestrator=orchestrator,
        )

        monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
        monkeypatch.setattr(
            integrator,
            "build_economic_context",
            lambda: EconomicContext(
                current_margin_pct=12.0,
                margin_target_pct=18.0,
                daily_revenue_usd=3200.0,
                cash_buffer_usd=50000.0,
                inventory_days_on_hand=4,
                stock_risk_level="high",
                active_promotions=0,
                advertising_spend_daily_usd=500.0,
                advertising_roas=1.2,
                customer_satisfaction_score=82.0,
                recent_anomalies=["margin_drop"],
            ),
        )

        result = integrator.process_cycle()

        assert result["orchestration"] is not None
        assert result["orchestration"]["approved_actions"]
        assert integrator.last_orchestration_plan is not None
