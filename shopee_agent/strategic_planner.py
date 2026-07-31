"""
Phase 38: Strategic planning for multi-step campaigns.

This module turns long-term goals into phased strategic plans, schedules them,
monitors progress, and adapts plans when the economic context changes.
"""

from __future__ import annotations

# asyncio not required here; remove unused import
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .agent_orchestrator import AgentOrchestrator
from .decision_engine import EconomicContext
from .logger import info


class PlanStatus(Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    AT_RISK = "at_risk"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


@dataclass
class Goal:
    name: str
    objective: str
    target_metrics: dict[str, float]
    budget: float
    duration_days: int
    priority: int = 3
    tags: list[str] = field(default_factory=list)


@dataclass
class Gate:
    gate_id: str
    name: str
    metric: str
    operator: str
    threshold: float
    required: bool = True

    def evaluate(self, value: float) -> bool:
        if self.operator == ">=":
            return value >= self.threshold
        if self.operator == ">":
            return value > self.threshold
        if self.operator == "<=":
            return value <= self.threshold
        if self.operator == "<":
            return value < self.threshold
        if self.operator == "==":
            return value == self.threshold
        return False


@dataclass
class PlanPhase:
    phase_id: str
    name: str
    duration_days: int
    actions: list[str]
    gates: list[Gate] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    owner: str = "strategic_planner"

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "name": self.name,
            "duration_days": self.duration_days,
            "actions": list(self.actions),
            "gates": [asdict(gate) for gate in self.gates],
            "dependencies": list(self.dependencies),
            "owner": self.owner,
        }


@dataclass
class StrategicPlan:
    plan_id: str
    name: str
    objective: str
    duration_days: int
    budget: float
    target_metrics: dict[str, float]
    phases: list[PlanPhase]
    dependencies: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    rollback_condition: str = ""
    status: PlanStatus = PlanStatus.PLANNED
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "objective": self.objective,
            "duration_days": self.duration_days,
            "budget": self.budget,
            "target_metrics": dict(self.target_metrics),
            "phases": [phase.to_dict() for phase in self.phases],
            "dependencies": list(self.dependencies),
            "success_criteria": list(self.success_criteria),
            "rollback_condition": self.rollback_condition,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class PlanTimelineEntry:
    phase_id: str
    name: str
    start_day: int
    end_day: int
    dependencies: list[str] = field(default_factory=list)


@dataclass
class PlanTimeline:
    plan_id: str
    entries: list[PlanTimelineEntry]
    total_duration_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "entries": [asdict(entry) for entry in self.entries],
            "total_duration_days": self.total_duration_days,
        }


@dataclass
class PlanAssessment:
    plan_id: str
    status: PlanStatus
    completed_gates: list[str] = field(default_factory=list)
    failing_gates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status.value,
            "completed_gates": list(self.completed_gates),
            "failing_gates": list(self.failing_gates),
            "notes": list(self.notes),
        }


class GoalStack:
    """Hierarchical goal stack for long-, medium-, and short-term planning."""

    def __init__(self, long_term: list[Goal] | None = None, medium_term: list[Goal] | None = None, short_term: list[Goal] | None = None):
        self.long_term = long_term or [
            Goal("Grow margin", "grow_margin_to_20", {"margin_pct": 20.0}, 2000.0, 90, priority=1, tags=["margin", "profitability"]),
            Goal("Launch product line", "launch_new_product_lines", {"new_lines": 3.0}, 5000.0, 60, priority=2, tags=["growth", "launch"]),
            Goal("Improve ROAS", "achieve_roas_2_5x", {"roas": 2.5}, 1500.0, 45, priority=2, tags=["ads", "efficiency"]),
        ]
        self.medium_term = medium_term or []
        self.short_term = short_term or []

    def top_goal(self) -> Goal | None:
        if not self.long_term:
            return None
        return sorted(self.long_term, key=lambda goal: goal.priority)[0]


class StrategicPlanner:
    """Decomposes goals into phases and monitors/adapts the resulting plan."""

    def __init__(self, orchestrator: AgentOrchestrator | None = None):
        self.orchestrator = orchestrator or AgentOrchestrator()

    def decompose_goal(self, goal: Goal, context: EconomicContext | None = None) -> StrategicPlan:
        objective = goal.objective.lower()
        if any(token in objective for token in ["margin", "profit", "profitability"]):
            phases = self._margin_plan(goal)
            criteria = ["margin_pct >= target", "no guardrail violations"]
            rollback = "Margin drops below 2pp of target for two consecutive checks"
        elif any(token in objective for token in ["launch", "campaign", "sale", "product"]):
            phases = self._launch_plan(goal)
            criteria = ["launch readiness complete", "campaign metrics within guardrails"]
            rollback = "Launch phase misses readiness gate or shows negative margin impact"
        elif any(token in objective for token in ["roas", "ads", "spend"]):
            phases = self._ads_plan(goal)
            criteria = ["roas improvement", "spend stays within budget"]
            rollback = "ROAS declines below baseline by 15%"
        else:
            phases = self._generic_plan(goal)
            criteria = ["goal-specific KPI improves", "campaign stays within budget"]
            rollback = "Context deteriorates and plan becomes non-viable"

        if context is not None:
            phases = self._tune_phases_for_context(phases, context)

        return StrategicPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            name=goal.name,
            objective=goal.objective,
            duration_days=goal.duration_days,
            budget=goal.budget,
            target_metrics=goal.target_metrics,
            phases=phases,
            dependencies=[],
            success_criteria=criteria,
            rollback_condition=rollback,
        )

    def schedule_phases(self, plan: StrategicPlan) -> PlanTimeline:
        entries: list[PlanTimelineEntry] = []
        cursor = 0
        phase_end_by_id: dict[str, int] = {}

        for phase in plan.phases:
            dependency_end = max((phase_end_by_id.get(dep, 0) for dep in phase.dependencies), default=0)
            start_day = max(cursor, dependency_end)
            end_day = start_day + max(1, phase.duration_days) - 1
            entries.append(
                PlanTimelineEntry(
                    phase_id=phase.phase_id,
                    name=phase.name,
                    start_day=start_day,
                    end_day=end_day,
                    dependencies=list(phase.dependencies),
                )
            )
            phase_end_by_id[phase.phase_id] = end_day + 1
            cursor = end_day + 1

        total = entries[-1].end_day + 1 if entries else 0
        return PlanTimeline(plan_id=plan.plan_id, entries=entries, total_duration_days=total)

    def monitor_plan(self, plan: StrategicPlan, context: EconomicContext) -> PlanAssessment:
        completed: list[str] = []
        failing: list[str] = []
        notes: list[str] = []

        for metric, target in plan.target_metrics.items():
            current = self._metric_value(context, metric)
            if current is None:
                notes.append(f"Missing metric: {metric}")
                continue

            if current >= target:
                completed.append(metric)
            else:
                failing.append(metric)

        if failing:
            status = PlanStatus.AT_RISK
            notes.append("One or more target metrics are below threshold")
        elif completed and len(completed) == len(plan.target_metrics):
            status = PlanStatus.COMPLETED
            notes.append("All target metrics met or exceeded")
        else:
            status = PlanStatus.ACTIVE
            notes.append("Plan is active and still accumulating signals")

        return PlanAssessment(
            plan_id=plan.plan_id,
            status=status,
            completed_gates=completed,
            failing_gates=failing,
            notes=notes,
        )

    def adapt_plan(self, plan: StrategicPlan, context: EconomicContext) -> StrategicPlan:
        assessment = self.monitor_plan(plan, context)
        plan.status = assessment.status
        plan.updated_at = datetime.now(UTC).isoformat()

        if assessment.status == PlanStatus.AT_RISK:
            for phase in plan.phases:
                if any(token in phase.name.lower() for token in ["pricing", "margin"]):
                    if "review metrics" not in phase.actions:
                        phase.actions.append("review metrics")
                if any(token in phase.name.lower() for token in ["ads", "growth"]):
                    phase.duration_days = max(1, int(round(phase.duration_days * 0.9)))
                if any(token in phase.name.lower() for token in ["launch", "campaign"]):
                    if "add rollback checkpoint" not in phase.actions:
                        phase.actions.append("add rollback checkpoint")
        return plan

    def create_plan_for_goal_stack(self, goal_stack: GoalStack, context: EconomicContext) -> StrategicPlan | None:
        goal = goal_stack.top_goal()
        if goal is None:
            return None
        plan = self.decompose_goal(goal, context=context)
        self.schedule_phases(plan)
        info("Strategic plan created", plan_id=plan.plan_id, goal=goal.name, phases=len(plan.phases))
        return plan

    def create_and_assess(self, goal_stack: GoalStack, context: EconomicContext) -> dict[str, Any]:
        plan = self.create_plan_for_goal_stack(goal_stack, context)
        if plan is None:
            return {"plan": None, "timeline": None, "assessment": None}

        timeline = self.schedule_phases(plan)
        assessment = self.monitor_plan(plan, context)
        plan = self.adapt_plan(plan, context)
        return {
            "plan": plan,
            "timeline": timeline,
            "assessment": assessment,
        }

    def _metric_value(self, context: EconomicContext, metric: str) -> float | None:
        normalized = metric.lower().strip()
        if normalized in {"margin", "margin_pct", "current_margin_pct"}:
            return float(context.current_margin_pct)
        if normalized in {"roas", "advertising_roas"}:
            return float(context.advertising_roas)
        if normalized in {"revenue", "daily_revenue_usd"}:
            return float(context.daily_revenue_usd)
        if normalized in {"cash_buffer", "cash_buffer_usd"}:
            return float(context.cash_buffer_usd)
        if normalized in {"inventory_days", "inventory_days_on_hand"}:
            return float(context.inventory_days_on_hand)
        if normalized in {"customer_satisfaction", "customer_satisfaction_score"}:
            return float(context.customer_satisfaction_score)
        return None

    def _tune_phases_for_context(self, phases: list[PlanPhase], context: EconomicContext) -> list[PlanPhase]:
        tuned = phases
        if context.current_margin_pct < context.margin_target_pct:
            for phase in tuned:
                if "pricing" in phase.name.lower() or "margin" in phase.name.lower():
                    if "protect margin first" not in phase.actions:
                        phase.actions.insert(0, "protect margin first")
        if context.inventory_days_on_hand <= 7:
            for phase in tuned:
                if "launch" in phase.name.lower() or "growth" in phase.name.lower():
                    if "pre-build stock buffer" not in phase.actions:
                        phase.actions.insert(0, "pre-build stock buffer")
        return tuned

    def _margin_plan(self, goal: Goal) -> list[PlanPhase]:
        return [
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_1",
                name="margin diagnosis",
                duration_days=max(7, goal.duration_days // 4),
                actions=["analyze margin drivers", "cluster low-margin SKUs", "validate guardrails"],
                gates=[Gate("gate_margin_baseline", "margin baseline", "margin_pct", ">=", goal.target_metrics.get("margin_pct", 20.0) - 5.0)],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_2",
                name="pricing optimization",
                duration_days=max(14, goal.duration_days // 2),
                actions=["raise prices on protected SKUs", "run elasticity checks", "apply phased rollout"],
                gates=[Gate("gate_margin_target", "margin target", "margin_pct", ">=", goal.target_metrics.get("margin_pct", 20.0))],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_1"],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_3",
                name="stabilization and review",
                duration_days=max(7, goal.duration_days // 4),
                actions=["lock in winning pricing rules", "review returns/refunds", "prepare next uplift"],
                gates=[Gate("gate_stability", "stability", "customer_satisfaction_score", ">=", 75.0)],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_2"],
            ),
        ]

    def _launch_plan(self, goal: Goal) -> list[PlanPhase]:
        return [
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_1",
                name="launch readiness",
                duration_days=max(10, goal.duration_days // 3),
                actions=["confirm inventory", "prepare assets", "align messaging"],
                gates=[Gate("gate_ready", "launch readiness", "inventory_days_on_hand", ">=", 10.0)],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_2",
                name="controlled launch",
                duration_days=max(14, goal.duration_days // 3),
                actions=["release to top SKUs", "monitor conversion", "cap promo spend"],
                gates=[Gate("gate_launch_margin", "launch margin", "margin_pct", ">=", 15.0)],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_1"],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_3",
                name="scale and optimize",
                duration_days=max(10, goal.duration_days // 3),
                actions=["expand to broader catalog", "increase budget gradually", "review learnings"],
                gates=[Gate("gate_scale_roas", "scale roas", "roas", ">=", 2.0)],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_2"],
            ),
        ]

    def _ads_plan(self, goal: Goal) -> list[PlanPhase]:
        return [
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_1",
                name="baseline audit",
                duration_days=max(7, goal.duration_days // 4),
                actions=["audit campaigns", "segment low roas ads", "freeze waste"],
                gates=[Gate("gate_roas_baseline", "roas baseline", "roas", ">=", 1.5)],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_2",
                name="budget reallocation",
                duration_days=max(14, goal.duration_days // 2),
                actions=["shift budget to winners", "test creative variants", "cap poor performers"],
                gates=[Gate("gate_roas_target", "roas target", "roas", ">=", goal.target_metrics.get("roas", 2.5))],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_1"],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_3",
                name="growth expansion",
                duration_days=max(7, goal.duration_days // 4),
                actions=["expand winners", "monitor marginal ROAS", "document rules"],
                gates=[Gate("gate_growth_safety", "growth safety", "margin_pct", ">=", 15.0)],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_2"],
            ),
        ]

    def _generic_plan(self, goal: Goal) -> list[PlanPhase]:
        return [
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_1",
                name="discovery",
                duration_days=max(5, goal.duration_days // 4),
                actions=["map current state", "identify bottlenecks", "confirm constraints"],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_2",
                name="execution",
                duration_days=max(10, goal.duration_days // 2),
                actions=["execute plan steps", "track KPIs", "adjust as needed"],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_1"],
            ),
            PlanPhase(
                phase_id=f"{goal.name.lower().replace(' ', '_')}_phase_3",
                name="review and scale",
                duration_days=max(5, goal.duration_days // 4),
                actions=["review outcomes", "codify learnings", "prepare next cycle"],
                dependencies=[f"{goal.name.lower().replace(' ', '_')}_phase_2"],
            ),
        ]
