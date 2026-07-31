"""
Phase 37: Multi-agent orchestration for competing business goals.

The orchestrator coordinates specialized agents, detects conflicts between their
proposals, and resolves them into a single execution plan.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from .decision_engine import EconomicContext
from .logger import info


@dataclass
class AgentAction:
    action_id: str
    agent_name: str
    action_type: str
    target: str
    direction: str
    magnitude: float
    priority: int = 3
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentProposal:
    agent_name: str
    actions: list[AgentAction] = field(default_factory=list)


@dataclass
class AgentConflict:
    target: str
    actions: list[AgentAction]
    reason: str


@dataclass
class Consensus:
    approved_actions: list[AgentAction] = field(default_factory=list)
    rejected_actions: list[AgentAction] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)
    conflicts: list[AgentConflict] = field(default_factory=list)
    rounds: int = 1
    consensus_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_actions": [action.to_dict() for action in self.approved_actions],
            "rejected_actions": [action.to_dict() for action in self.rejected_actions],
            "tradeoffs": list(self.tradeoffs),
            "conflicts": [
                {
                    "target": conflict.target,
                    "reason": conflict.reason,
                    "actions": [action.to_dict() for action in conflict.actions],
                }
                for conflict in self.conflicts
            ],
            "rounds": self.rounds,
            "consensus_score": self.consensus_score,
        }


@dataclass
class ExecutionPlan:
    plan_id: str
    approved_actions: list[AgentAction]
    rejected_actions: list[AgentAction]
    tradeoffs: list[str]
    conflicts: list[AgentConflict]
    schedule: list[str]
    consensus_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "approved_actions": [action.to_dict() for action in self.approved_actions],
            "rejected_actions": [action.to_dict() for action in self.rejected_actions],
            "tradeoffs": list(self.tradeoffs),
            "conflicts": [
                {
                    "target": conflict.target,
                    "reason": conflict.reason,
                    "actions": [action.to_dict() for action in conflict.actions],
                }
                for conflict in self.conflicts
            ],
            "schedule": list(self.schedule),
            "consensus_score": self.consensus_score,
        }


class LauraAgent(ABC):
    name: str = "agent"
    objectives: list[str] = []
    constraints: dict[str, Any] = {}
    weight: float = 1.0

    @abstractmethod
    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        raise NotImplementedError


class PricingAgent(LauraAgent):
    name = "pricing_agent"
    objectives = ["maximize_margin", "maintain_velocity"]
    weight = 1.0

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        gap = context.margin_target_pct - context.current_margin_pct
        if gap <= 0:
            return []

        magnitude = min(0.08, max(0.02, gap / 100.0))
        return [
            AgentAction(
                action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                agent_name=self.name,
                action_type="price_adjustment",
                target="pricing",
                direction="up",
                magnitude=magnitude,
                priority=1,
                rationale=f"Margin gap of {gap:.1f}pp requires price protection.",
            )
        ]


class AdsAgent(LauraAgent):
    name = "ads_agent"
    objectives = ["maximize_roas", "spend_budget"]
    weight = 0.9

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        actions: list[AgentAction] = []
        if context.advertising_roas < 1.6:
            actions.append(
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="ad_spend_adjustment",
                    target="ads_budget",
                    direction="down",
                    magnitude=min(0.25, max(0.1, (1.6 - context.advertising_roas) / 4.0)),
                    priority=2,
                    rationale=f"ROAS {context.advertising_roas:.2f} is below target.",
                )
            )
        elif context.advertising_roas > 2.5 and context.current_margin_pct >= context.margin_target_pct:
            actions.append(
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="ad_spend_adjustment",
                    target="ads_budget",
                    direction="up",
                    magnitude=0.10,
                    priority=2,
                    rationale="High ROAS and healthy margin support a budget increase.",
                )
            )
        return actions


class InventoryAgent(LauraAgent):
    name = "inventory_agent"
    objectives = ["prevent_stockout", "minimize_carrying_cost"]
    weight = 0.95

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        if context.inventory_days_on_hand <= 7 or context.stock_risk_level in {"critical", "high"}:
            return [
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="inventory_replenishment",
                    target="inventory",
                    direction="up",
                    magnitude=0.20,
                    priority=1,
                    rationale=f"Inventory cover is {context.inventory_days_on_hand} days and risk is {context.stock_risk_level}.",
                )
            ]
        return []


class RevenueAgent(LauraAgent):
    name = "revenue_agent"
    objectives = ["maximize_gmv", "balance_margin"]
    weight = 0.95

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        actions: list[AgentAction] = []
        if context.daily_revenue_usd < 4500 and context.current_margin_pct <= context.margin_target_pct:
            actions.append(
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="price_adjustment",
                    target="pricing",
                    direction="down",
                    magnitude=0.04,
                    priority=2,
                    rationale="Low revenue suggests a small demand-side price move.",
                )
            )
        if context.customer_satisfaction_score >= 75 and context.advertising_roas >= 2.0:
            actions.append(
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="growth_investment",
                    target="ads_budget",
                    direction="up",
                    magnitude=0.08,
                    priority=3,
                    rationale="Customer sentiment and ROAS can support measured growth spend.",
                )
            )
        return actions


class CompetitorAgent(LauraAgent):
    name = "competitor_agent"
    objectives = ["track_competitor_moves", "protect_share"]
    weight = 0.85

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        if not any(
            marker in " ".join(context.recent_anomalies).lower()
            for marker in ["competitor", "price_pressure", "rank_drop", "share_loss"]
        ):
            return []

        return [
            AgentAction(
                action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                agent_name=self.name,
                action_type="price_match",
                target="pricing",
                direction="down",
                magnitude=0.03,
                priority=2,
                rationale="Competitor pressure detected in recent anomalies; defend price competitiveness.",
            )
        ]


class GrowthAgent(LauraAgent):
    name = "growth_agent"
    objectives = ["expand_revenue", "scale_what_works"]
    weight = 0.9

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        if context.customer_satisfaction_score < 78 or context.advertising_roas < 2.0:
            return []

        return [
            AgentAction(
                action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                agent_name=self.name,
                action_type="growth_investment",
                target="ads_budget",
                direction="up",
                magnitude=0.12,
                priority=3,
                rationale="Strong customer sentiment and ROAS support a measured growth push.",
            )
        ]


class FinanceAgent(LauraAgent):
    name = "finance_agent"
    objectives = ["preserve_cash", "stabilize_runway"]
    weight = 0.92

    async def plan(self, context: EconomicContext) -> list[AgentAction]:
        actions: list[AgentAction] = []

        if context.cash_buffer_usd < 20000:
            actions.append(
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="cost_containment",
                    target="opex",
                    direction="down",
                    magnitude=0.15,
                    priority=1,
                    rationale="Cash buffer is tight; reduce discretionary operating spend.",
                )
            )

        if context.cash_buffer_usd >= 50000 and context.current_margin_pct >= context.margin_target_pct:
            actions.append(
                AgentAction(
                    action_id=f"{self.name}-{uuid.uuid4().hex[:8]}",
                    agent_name=self.name,
                    action_type="reserve_optimization",
                    target="cash_buffer",
                    direction="up",
                    magnitude=0.08,
                    priority=3,
                    rationale="Healthy runway allows a modest reserve increase.",
                )
            )

        return actions


class AgentOrchestrator:
    """Coordinates specialized agents and resolves competing proposals."""

    def __init__(
        self,
        agents: list[LauraAgent] | None = None,
        business_weights: dict[str, float] | None = None,
    ):
        if agents is None:
            agents = [
                PricingAgent(),
                AdsAgent(),
                InventoryAgent(),
                RevenueAgent(),
                CompetitorAgent(),
                GrowthAgent(),
                FinanceAgent(),
            ]

        self.agents = {agent.name: agent for agent in agents}
        self.business_weights = business_weights or {
            "pricing_agent": 1.0,
            "ads_agent": 0.9,
            "inventory_agent": 0.95,
            "revenue_agent": 0.95,
            "competitor_agent": 0.85,
            "growth_agent": 0.9,
            "finance_agent": 0.92,
        }

    async def coordinate_cycle(self, context: EconomicContext) -> ExecutionPlan:
        proposals = await asyncio.gather(*[agent.plan(context) for agent in self.agents.values()])
        flat_actions = [action for agent_actions in proposals for action in agent_actions]
        consensus = self._resolve(flat_actions)

        plan = ExecutionPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:10]}",
            approved_actions=consensus.approved_actions,
            rejected_actions=consensus.rejected_actions,
            tradeoffs=consensus.tradeoffs,
            conflicts=consensus.conflicts,
            schedule=[action.action_id for action in self._schedule(consensus.approved_actions)],
            consensus_score=consensus.consensus_score,
        )
        info(
            "Agent orchestration complete",
            agents=len(self.agents),
            approved=len(plan.approved_actions),
            rejected=len(plan.rejected_actions),
            conflicts=len(plan.conflicts),
        )
        return plan

    def coordinate_cycle_sync(self, context: EconomicContext) -> ExecutionPlan:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                import threading
                result: list[ExecutionPlan] = []
                exc_info: list[BaseException] = []
                def _run():
                    try:
                        result.append(asyncio.run(self.coordinate_cycle(context)))
                    except BaseException as e:
                        exc_info.append(e)
                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=60)
                if exc_info:
                    raise exc_info[0]
                return result[0]
        except RuntimeError:
            pass
        return asyncio.run(self.coordinate_cycle(context))

    def _resolve(self, actions: list[AgentAction]) -> Consensus:
        if not actions:
            return Consensus(consensus_score=1.0)

        groups: dict[str, list[AgentAction]] = {}
        for action in actions:
            groups.setdefault(action.target, []).append(action)

        approved: list[AgentAction] = []
        rejected: list[AgentAction] = []
        tradeoffs: list[str] = []
        conflicts: list[AgentConflict] = []

        for target, group in groups.items():
            if len({action.direction for action in group}) == 1:
                winner = max(group, key=self._score)
                approved.append(winner)
                rejected.extend(action for action in group if action is not winner)
                continue

            conflicts.append(
                AgentConflict(
                    target=target,
                    actions=list(group),
                    reason=f"Competing directions for {target}",
                )
            )

            direction_scores: dict[str, float] = {}
            for action in group:
                direction_scores[action.direction] = direction_scores.get(action.direction, 0.0) + self._score(action)

            winning_direction = max(direction_scores.items(), key=lambda item: item[1])[0]
            winner_candidates = [action for action in group if action.direction == winning_direction]
            winner = max(winner_candidates, key=self._score)
            approved.append(winner)

            for action in group:
                if action is not winner:
                    rejected.append(action)
                    tradeoffs.append(
                        f"{action.agent_name} ceded on {target}: {action.direction} vs {winner.direction}"
                    )

        consensus_score = len(approved) / len(actions)
        return Consensus(
            approved_actions=self._dedupe(approved),
            rejected_actions=self._dedupe(rejected),
            tradeoffs=tradeoffs,
            conflicts=conflicts,
            rounds=1,
            consensus_score=consensus_score,
        )

    def _score(self, action: AgentAction) -> float:
        base = self.business_weights.get(action.agent_name, 1.0)
        priority_bonus = max(0.0, 4 - float(action.priority)) * 0.1
        return base + priority_bonus + action.magnitude

    def _schedule(self, actions: list[AgentAction]) -> list[AgentAction]:
        return sorted(actions, key=lambda action: (action.priority, -self._score(action), action.agent_name))

    @staticmethod
    def _dedupe(actions: list[AgentAction]) -> list[AgentAction]:
        seen: set[str] = set()
        result: list[AgentAction] = []
        for action in actions:
            if action.action_id in seen:
                continue
            seen.add(action.action_id)
            result.append(action)
        return result
