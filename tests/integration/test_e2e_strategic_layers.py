from __future__ import annotations

"""Testes de integracao das fases 37-41: orquestracao multi-agente, plano
estrategico, analytics preditivo, inteligencia competitiva e supply chain
conectados ao DecisionIntegrator e ao loop autonomo."""

import json
from pathlib import Path

import pytest

from shopee_agent.agent_orchestrator import AgentOrchestrator
from shopee_agent.autonomous_strategy import AutonomousStrategyLayer
from shopee_agent.competitive_intelligence import CompetitiveIntelligence
from shopee_agent.decision_engine import default_economic_context
from shopee_agent.predictive_analytics import PredictiveAnalytics
from shopee_agent.strategic_planner import (
    Goal,
    GoalStack,
    StrategicPlanner,
)
from shopee_agent.supply_chain_planner_v2 import SupplyChainPlannerV2


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    return tmp_path / "reports"


@pytest.mark.integration
def test_orchestrator_produces_consensus_plan() -> None:
    """Fase 37: orquestrador gera plano com consenso entre agentes em conflito."""
    orchestrator = AgentOrchestrator()
    ctx = default_economic_context()

    plan = orchestrator.coordinate_cycle_sync(ctx)

    assert plan is not None
    assert hasattr(plan, "approved_actions")
    assert hasattr(plan, "rejected_actions")
    assert plan.consensus_score >= 0.0
    for action in plan.approved_actions:
        assert action.agent_name
        assert action.direction in ("up", "down", "none")


@pytest.mark.integration
def test_strategic_planner_goal_to_plan() -> None:
    """Fase 38: meta de longo prazo vira plano multi-fase com gates."""
    planner = StrategicPlanner()
    goal = Goal(
        name="crescer_margem",
        objective="Elevar margem de 15% para 20%",
        target_metrics={"margin": 20.0},
        budget=1000.0,
        duration_days=30,
    )

    plan = planner.decompose_goal(goal)

    assert plan is not None
    assert plan.name == "crescer_margem"
    assert len(plan.phases) >= 1
    assert plan.rollback_condition


@pytest.mark.integration
def test_predictive_analytics_forecast_overview(reports_dir: Path) -> None:
    """Fase 39: snapshot preditivo (revenue/margin/roas) a partir de historico local."""
    pa = PredictiveAnalytics(reports_dir=str(reports_dir))
    history = reports_dir / "laura_profitability_history.jsonl"
    for i in range(1, 11):
        history.write_text(
            json.dumps(
                {
                    "metrics": {
                        "daily_revenue_usd": 9.0 + i,
                        "gross_margin_pct": 15.0 + i * 0.2,
                        "actual_roas": 2.0 + i * 0.07,
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )

    snapshot = pa.forecast_overview(horizon_days=7)

    assert snapshot is not None
    assert len(snapshot.forecasts) >= 1
    json.dumps(snapshot.to_dict())


@pytest.mark.integration
def test_competitive_intelligence_snapshot(reports_dir: Path) -> None:
    """Fase 40: registro de oferta de concorrente gera snapshot acionavel."""
    ci = CompetitiveIntelligence(path=str(reports_dir / "competitive_offers.jsonl"))

    ci.record_offer(
        competitor_name="Concorrente X",
        item_id="item_123",
        item_name="Produto Teste",
        competitor_price=9.9,
        our_price=15.0,
    )
    snapshot = ci.snapshot()

    assert snapshot is not None
    assert snapshot.total_offers >= 1
    json.dumps(snapshot.to_dict())


@pytest.mark.integration
def test_supply_chain_v2_analyze_chain() -> None:
    """Fase 41: supplier scoring + recomendacao de reposicao."""
    sc = SupplyChainPlannerV2()

    result = sc.analyze_chain(
        {
            "suppliers": [
                {
                    "name": "Fornecedor A",
                    "price": 10.0,
                    "lead_time_days": 5,
                    "reliability": 0.9,
                },
                {
                    "name": "Fornecedor B",
                    "price": 8.0,
                    "lead_time_days": 12,
                    "reliability": 0.6,
                },
            ],
            "orders": [
                {"item_id": "i1", "quantity": 10, "warehouse": "w1"},
            ],
            "warehouses": [
                {"id": "w1", "stock": 50},
                {"id": "w2", "stock": 5},
            ],
        }
    )

    assert result is not None
    assert result["suppliers_scored"] >= 1
    assert isinstance(result["top_suppliers"], list)


@pytest.mark.integration
def test_autonomous_strategy_snapshot(reports_dir: Path) -> None:
    """Camada estrategica: snapshot unificado das fases 38-40."""
    layer = AutonomousStrategyLayer(
        goal_stack=GoalStack(),
        strategic_planner=StrategicPlanner(),
        predictive_analytics=PredictiveAnalytics(reports_dir=str(reports_dir)),
        competitive_intelligence=CompetitiveIntelligence(
            path=str(reports_dir / "competitive_offers.jsonl")
        ),
    )

    snapshot = layer.evaluate(default_economic_context(), horizon_days=14)

    assert snapshot is not None
    payload = snapshot.to_dict()
    assert isinstance(payload, dict)
    json.dumps(payload)
