"""
Phase 9: Autonomous Strategy Layer.

Synthesizes long-term goals, strategic plans, predictive analytics, and
economic context into actionable growth strategies for expansion, seasonal
planning, category exploration, and margin protection.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .branding_growth import BrandingGrowthAnalyzer, BrandingGrowthSnapshot
from .cognitive_memory import LongTermMemory
from .competitive_intelligence import CompetitiveIntelligence, CompetitiveSnapshot
from .decision_engine import EconomicContext
from .goal_management import GoalManager
from .predictive_analytics import PredictiveAnalytics, PredictiveSnapshot
from .strategic_planner import GoalStack, PlanAssessment, PlanTimeline, StrategicPlan, StrategicPlanner


@dataclass
class StrategySignal:
    name: str
    value: float
    severity: str = "normal"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyScenario:
    name: str
    objective: str
    priority: str
    actions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    expected_impact: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomousStrategySnapshot:
    generated_at: str
    status: str
    horizon_days: int
    top_goal: dict[str, Any] | None
    signals: list[StrategySignal]
    scenarios: list[StrategyScenario]
    strategic_plan: dict[str, Any] | None
    plan_timeline: dict[str, Any] | None
    plan_assessment: dict[str, Any] | None
    predictive_snapshot: dict[str, Any] | None
    competitive_snapshot: dict[str, Any] | None
    branding_snapshot: dict[str, Any] | None
    recommendations: list[str] = field(default_factory=list)
    watchpoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "status": self.status,
            "horizon_days": self.horizon_days,
            "top_goal": self.top_goal,
            "signals": [signal.to_dict() for signal in self.signals],
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "strategic_plan": self.strategic_plan,
            "plan_timeline": self.plan_timeline,
            "plan_assessment": self.plan_assessment,
            "predictive_snapshot": self.predictive_snapshot,
            "competitive_snapshot": self.competitive_snapshot,
            "branding_snapshot": self.branding_snapshot,
            "recommendations": list(self.recommendations),
            "watchpoints": list(self.watchpoints),
        }


class AutonomousStrategyLayer:
    """Deterministic strategy synthesis over the existing cognitive stack."""

    def __init__(
        self,
        goal_stack: GoalStack | None = None,
        strategic_planner: StrategicPlanner | None = None,
        goal_manager: GoalManager | None = None,
        predictive_analytics: PredictiveAnalytics | None = None,
        competitive_intelligence: CompetitiveIntelligence | None = None,
        branding_growth: BrandingGrowthAnalyzer | None = None,
        memory: LongTermMemory | None = None,
    ):
        self.goal_stack = goal_stack or GoalStack()
        self.goal_manager = goal_manager or GoalManager.from_goal_stack(self.goal_stack)
        self.strategic_planner = strategic_planner or StrategicPlanner()
        self.predictive_analytics = predictive_analytics or PredictiveAnalytics()
        self.competitive_intelligence = competitive_intelligence or CompetitiveIntelligence()
        self.branding_growth = branding_growth or BrandingGrowthAnalyzer()
        self.memory = memory or LongTermMemory()

    def evaluate(self, context: EconomicContext, horizon_days: int = 30) -> AutonomousStrategySnapshot:
        top_goal = self.goal_stack.top_goal()
        top_goal_payload = top_goal.__dict__ if top_goal is not None else None

        strategic_result = self.strategic_planner.create_and_assess(self.goal_stack, context)
        plan: StrategicPlan | None = strategic_result.get("plan")
        timeline: PlanTimeline | None = strategic_result.get("timeline")
        assessment: PlanAssessment | None = strategic_result.get("assessment")

        predictive_snapshot: PredictiveSnapshot = self.predictive_analytics.forecast_overview(horizon_days=horizon_days)
        competitive_snapshot: CompetitiveSnapshot = self.competitive_intelligence.snapshot()
        branding_snapshot: BrandingGrowthSnapshot = self.branding_growth.snapshot()

        signals = self._derive_signals(context, predictive_snapshot, competitive_snapshot, branding_snapshot)
        scenarios = self._build_scenarios(context, predictive_snapshot, competitive_snapshot)

        recommendations = self._recommendations(context, predictive_snapshot, competitive_snapshot, branding_snapshot, assessment)
        watchpoints = self._watchpoints(context, predictive_snapshot, competitive_snapshot, branding_snapshot)
        status = self._status_from_signals(signals, assessment)

        snapshot = AutonomousStrategySnapshot(
            generated_at=datetime.now(UTC).isoformat(),
            status=status,
            horizon_days=horizon_days,
            top_goal=top_goal_payload,
            signals=signals,
            scenarios=scenarios,
            strategic_plan=plan.to_dict() if plan is not None else None,
            plan_timeline=timeline.to_dict() if timeline is not None else None,
            plan_assessment=assessment.to_dict() if assessment is not None else None,
            predictive_snapshot=predictive_snapshot.to_dict(),
            competitive_snapshot=competitive_snapshot.to_dict(),
            branding_snapshot=branding_snapshot.to_dict(),
            recommendations=recommendations,
            watchpoints=watchpoints,
        )

        self.memory.remember_note(
            kind="strategy_cycle",
            title=f"Autonomous strategy {horizon_days}d",
            summary=self._summarize_snapshot(snapshot),
            metadata={
                "status": snapshot.status,
                "horizon_days": horizon_days,
                "watchpoints": watchpoints,
                "signals": [signal.to_dict() for signal in signals],
            },
        )

        return snapshot

    def evaluate_goal(self, horizon_days: int = 30) -> AutonomousStrategySnapshot:
        context = self._default_context()
        return self.evaluate(context=context, horizon_days=horizon_days)

    def _derive_signals(
        self,
        context: EconomicContext,
        predictive_snapshot: PredictiveSnapshot,
        competitive_snapshot: CompetitiveSnapshot,
        branding_snapshot: BrandingGrowthSnapshot,
    ) -> list[StrategySignal]:
        signals: list[StrategySignal] = []

        if context.current_margin_pct < context.margin_target_pct:
            signals.append(StrategySignal("margin_gap", context.margin_target_pct - context.current_margin_pct, "high", {"current_margin_pct": context.current_margin_pct, "margin_target_pct": context.margin_target_pct}))
        if context.advertising_roas < 2.0:
            signals.append(StrategySignal("roas_pressure", 2.0 - context.advertising_roas, "high", {"advertising_roas": context.advertising_roas}))
        if context.inventory_days_on_hand <= 7:
            signals.append(StrategySignal("inventory_pressure", float(context.inventory_days_on_hand), "medium", {"inventory_days_on_hand": context.inventory_days_on_hand}))

        for forecast in predictive_snapshot.forecasts:
            if forecast.risk_level in {"high", "critical"}:
                signals.append(StrategySignal(f"forecast_{forecast.metric}_risk", forecast.forecast_value, "high", forecast.to_dict()))

        if competitive_snapshot.threat_count > 0:
            signals.append(
                StrategySignal(
                    "competitive_threat",
                    float(competitive_snapshot.threat_count),
                    "high",
                    {
                        "threat_count": competitive_snapshot.threat_count,
                        "average_gap_pct": competitive_snapshot.average_gap_pct,
                        "threats": competitive_snapshot.threats[:5],
                    },
                )
            )

        if competitive_snapshot.opportunity_count > 0:
            signals.append(
                StrategySignal(
                    "competitive_opportunity",
                    float(competitive_snapshot.opportunity_count),
                    "medium",
                    {
                        "opportunity_count": competitive_snapshot.opportunity_count,
                        "average_gap_pct": competitive_snapshot.average_gap_pct,
                        "opportunities": competitive_snapshot.opportunities[:5],
                    },
                )
            )

        if branding_snapshot.recommendations:
            signals.append(StrategySignal("branding_opportunity", float(len(branding_snapshot.recommendations)), "medium", branding_snapshot.to_dict()))

        return signals

    def _build_scenarios(
        self,
        context: EconomicContext,
        predictive_snapshot: PredictiveSnapshot,
        competitive_snapshot: CompetitiveSnapshot,
    ) -> list[StrategyScenario]:
        scenarios: list[StrategyScenario] = []

        scenarios.append(
            StrategyScenario(
                name="margin_protection",
                objective="preserve margin while maintaining velocity",
                priority="high" if context.current_margin_pct < context.margin_target_pct else "medium",
                actions=["reprice weak SKUs", "protect hero products", "monitor refunds"],
                risks=["revenue softness", "competitive undercutting"],
                expected_impact={"margin_pct": 0.03, "roas": 0.05},
            )
        )

        scenarios.append(
            StrategyScenario(
                name="growth_push",
                objective="scale validated products and campaigns",
                priority="high" if context.customer_satisfaction_score >= 80 and context.advertising_roas >= 2.0 else "medium",
                actions=["expand budget to winners", "increase inventory buffer", "launch cross-sell bundles"],
                risks=["inventory shortages", "margin dilution"],
                expected_impact={"revenue": 0.08, "roas": 0.04},
            )
        )

        if predictive_snapshot.risks:
            scenarios.append(
                StrategyScenario(
                    name="seasonal_defense",
                    objective="prepare for seasonal dips and volatility",
                    priority="high",
                    actions=["build cash buffer", "slow non-essential spend", "pre-book replenishment"],
                    risks=list(predictive_snapshot.risks),
                    expected_impact={"cash_buffer": 0.05, "inventory_days_on_hand": 0.05},
                )
            )

        if competitive_snapshot.threat_count > 0:
            scenarios.append(
                StrategyScenario(
                    name="competitive_response",
                    objective="respond to price and ranking threats",
                    priority="high",
                    actions=["track competitor price moves", "protect ranking on key SKUs", "adjust ads budget selectively"],
                    risks=["margin compression", "share loss"],
                    expected_impact={"share_protection": 0.05},
                )
            )

        return scenarios

    def _recommendations(
        self,
        context: EconomicContext,
        predictive_snapshot: PredictiveSnapshot,
        competitive_snapshot: CompetitiveSnapshot,
        branding_snapshot: BrandingGrowthSnapshot,
        assessment: PlanAssessment | None,
    ) -> list[str]:
        recommendations: list[str] = []

        if context.current_margin_pct < context.margin_target_pct:
            recommendations.append("Priorize proteção de margem antes de ampliar investimento.")
        if context.advertising_roas >= 2.0:
            recommendations.append("Escale campanhas vencedoras com aumento gradual de orçamento.")
        if context.inventory_days_on_hand <= 7:
            recommendations.append("Crie estoque de segurança para suportar crescimento.")
        if predictive_snapshot.risks:
            recommendations.append("Use a previsão para antecipar risco sazonal e ajustar o ritmo de expansão.")
        if competitive_snapshot.threat_count > 0:
            recommendations.append("Reaja às ameaças competitivas monitorando preço e ranking dos SKUs centrais.")
        if branding_snapshot.recommendations:
            recommendations.extend(branding_snapshot.recommendations[:2])
        if assessment and assessment.status.value == "at_risk":
            recommendations.append("Reforce o plano estratégico atual com checkpoints de rollback e gatilhos de revisão.")

        return self._dedupe(recommendations)

    def _watchpoints(
        self,
        context: EconomicContext,
        predictive_snapshot: PredictiveSnapshot,
        competitive_snapshot: CompetitiveSnapshot,
        branding_snapshot: BrandingGrowthSnapshot,
    ) -> list[str]:
        watchpoints: list[str] = []
        if context.cash_buffer_usd < 20000:
            watchpoints.append("cash buffer below safety threshold")
        if context.current_margin_pct < context.margin_target_pct:
            watchpoints.append("margin gap requires protection before scaling")
        if context.advertising_roas >= 2.0 and context.customer_satisfaction_score >= 80:
            watchpoints.append("growth window is open for controlled expansion")
        if any(forecast.metric == "revenue" and forecast.risk_level in {"high", "critical"} for forecast in predictive_snapshot.forecasts):
            watchpoints.append("revenue forecast risk")
        if competitive_snapshot.threat_count > 0:
            watchpoints.append("competitive pressure on key SKUs")
        if branding_snapshot.recommendations:
            watchpoints.append("growth opportunities ready for activation")
        if not watchpoints:
            watchpoints.append("review strategic signals before the next cycle")
        return watchpoints

    def _status_from_signals(self, signals: list[StrategySignal], assessment: PlanAssessment | None) -> str:
        if assessment and assessment.status.value == "at_risk":
            return "at_risk"
        if any(signal.severity in {"high", "critical"} for signal in signals):
            return "needs_attention"
        if signals:
            return "ready_for_growth"
        return "stable"

    def _summarize_snapshot(self, snapshot: AutonomousStrategySnapshot) -> str:
        return (
            f"status={snapshot.status}; signals={len(snapshot.signals)}; scenarios={len(snapshot.scenarios)}; "
            f"recommendations={len(snapshot.recommendations)}"
        )

    def _default_context(self) -> EconomicContext:
        return EconomicContext(
            current_margin_pct=16.0,
            margin_target_pct=18.0,
            daily_revenue_usd=3200.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=12,
            stock_risk_level="normal",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=2.0,
            customer_satisfaction_score=82.0,
            recent_anomalies=[],
        )

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result


def dump_strategy_snapshot(snapshot: AutonomousStrategySnapshot, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
