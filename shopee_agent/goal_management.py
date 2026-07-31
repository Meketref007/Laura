from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import GOALS_STATE

from .decision_engine import EconomicContext
from .strategic_planner import Goal, GoalStack


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _goal_text(goal: Goal) -> str:
    return " ".join(
        [
            goal.name,
            goal.objective,
            " ".join(goal.tags),
            " ".join(goal.target_metrics.keys()),
        ]
    ).lower()


@dataclass
class ManagedGoal:
    goal_id: str
    name: str
    objective: str
    target_metrics: dict[str, float]
    budget: float
    duration_days: int
    priority: int = 3
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    score: float = 0.0
    notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now().isoformat())
    updated_at: str = field(default_factory=lambda: _utc_now().isoformat())

    @classmethod
    def from_goal(cls, goal: Goal, status: str = "active") -> ManagedGoal:
        return cls(
            goal_id=f"goal_{uuid.uuid4().hex[:10]}",
            name=goal.name,
            objective=goal.objective,
            target_metrics=dict(goal.target_metrics),
            budget=float(goal.budget),
            duration_days=int(goal.duration_days),
            priority=int(goal.priority),
            tags=list(goal.tags),
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PriorityEngine:
    """Score goals so the most urgent and valuable ones surface first."""

    def score_goal(self, goal: ManagedGoal, context: EconomicContext | None = None) -> tuple[float, list[str]]:
        reasons: list[str] = []

        priority_bonus = max(0.0, 4 - float(goal.priority)) * 18.0
        reasons.append(f"priority_bonus={priority_bonus:.1f}")

        urgency_bonus = max(0.0, 90.0 - float(goal.duration_days)) * 0.4
        reasons.append(f"urgency_bonus={urgency_bonus:.1f}")

        budget_bonus = max(0.0, 30.0 - float(goal.budget) / 250.0)
        reasons.append(f"budget_bonus={budget_bonus:.1f}")

        context_bonus = 0.0
        objective_text = _goal_text(Goal(goal.name, goal.objective, goal.target_metrics, goal.budget, goal.duration_days, goal.priority, goal.tags))
        if context is not None:
            if any(token in objective_text for token in {"margin", "profit", "profitability"}):
                margin_gap = max(0.0, context.margin_target_pct - context.current_margin_pct)
                context_bonus += min(25.0, margin_gap * 4.0)
                reasons.append(f"margin_gap={margin_gap:.1f}")
            if any(token in objective_text for token in {"roas", "ads", "spend"}):
                roas_gap = max(0.0, 2.5 - context.advertising_roas)
                context_bonus += min(20.0, roas_gap * 12.0)
                reasons.append(f"roas_gap={roas_gap:.2f}")
            if any(token in objective_text for token in {"stock", "inventory", "restock"}):
                inventory_gap = max(0.0, 10.0 - float(context.inventory_days_on_hand))
                context_bonus += min(20.0, inventory_gap * 2.0)
                reasons.append(f"inventory_gap={inventory_gap:.1f}")

        score = min(100.0, priority_bonus + urgency_bonus + budget_bonus + context_bonus)
        return score, reasons

    def rank_goals(
        self,
        goals: list[ManagedGoal],
        context: EconomicContext | None = None,
    ) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for goal in goals:
            score, reasons = self.score_goal(goal, context)
            ranked.append(
                {
                    "goal": goal.to_dict(),
                    "score": score,
                    "reasons": reasons,
                }
            )

        ranked.sort(key=lambda item: (-item["score"], item["goal"]["priority"], item["goal"]["duration_days"]))
        return ranked


class GoalManager:
    """Persistent goal registry backed by JSONL."""

    def __init__(self, path: str = str(GOALS_STATE)):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._goals: list[ManagedGoal] = []
        self._load()

    @classmethod
    def from_goal_stack(cls, goal_stack: GoalStack, path: str = str(GOALS_STATE)) -> GoalManager:
        manager = cls(path=path)
        if not manager._goals:
            for goal in goal_stack.long_term:
                manager.add_goal(goal, persist=True)
        return manager

    def _load(self) -> None:
        if not self.path.exists():
            return

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    try:
                        payload = json.loads(raw_line)
                        self._goals.append(
                            ManagedGoal(
                                goal_id=str(payload.get("goal_id", f"goal_{uuid.uuid4().hex[:10]}")),
                                name=str(payload.get("name", "")),
                                objective=str(payload.get("objective", "")),
                                target_metrics=dict(payload.get("target_metrics", {})),
                                budget=float(payload.get("budget", 0.0)),
                                duration_days=int(payload.get("duration_days", 0)),
                                priority=int(payload.get("priority", 3)),
                                tags=list(payload.get("tags", [])),
                                status=str(payload.get("status", "active")),
                                score=float(payload.get("score", 0.0)),
                                notes=list(payload.get("notes", [])),
                                created_at=str(payload.get("created_at", _utc_now().isoformat())),
                                updated_at=str(payload.get("updated_at", _utc_now().isoformat())),
                            )
                        )
                    except Exception:
                        continue
        except Exception:
            self._goals = []

    def _persist(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for goal in self._goals:
                handle.write(json.dumps(goal.to_dict(), ensure_ascii=False) + "\n")

    def add_goal(self, goal: Goal, persist: bool = True, status: str = "active") -> ManagedGoal:
        managed_goal = ManagedGoal.from_goal(goal, status=status)
        self._goals.append(managed_goal)
        if persist:
            self._persist()
        return managed_goal

    def list_goals(self, status: str | None = None) -> list[ManagedGoal]:
        goals = list(self._goals)
        if status is not None:
            goals = [goal for goal in goals if goal.status == status]
        return goals

    def register_goal(
        self,
        name: str,
        objective: str,
        target_metrics: dict[str, float],
        budget: float,
        duration_days: int,
        priority: int = 3,
        tags: list[str] | None = None,
        status: str = "active",
    ) -> ManagedGoal:
        goal = Goal(
            name=name,
            objective=objective,
            target_metrics=target_metrics,
            budget=budget,
            duration_days=duration_days,
            priority=priority,
            tags=list(tags or []),
        )
        return self.add_goal(goal, persist=True, status=status)

    def complete_goal(self, goal_id: str, note: str | None = None) -> ManagedGoal | None:
        for goal in self._goals:
            if goal.goal_id == goal_id:
                goal.status = "completed"
                goal.updated_at = _utc_now().isoformat()
                if note:
                    goal.notes.append(note)
                self._persist()
                return goal
        return None

    def top_goal(
        self,
        context: EconomicContext | None = None,
        priority_engine: PriorityEngine | None = None,
    ) -> ManagedGoal | None:
        ranked = self.rank_goals(context=context, priority_engine=priority_engine)
        return ranked[0]["goal_obj"] if ranked else None

    def rank_goals(
        self,
        context: EconomicContext | None = None,
        priority_engine: PriorityEngine | None = None,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        engine = priority_engine or PriorityEngine()
        goals = self.list_goals(status=status)
        ranked = engine.rank_goals(goals, context=context)
        enriched: list[dict[str, Any]] = []
        for item in ranked:
            goal_obj = next((goal for goal in goals if goal.goal_id == item["goal"]["goal_id"]), None)
            enriched.append({**item, "goal_obj": goal_obj})
        return enriched

    def snapshot(
        self,
        context: EconomicContext | None = None,
        priority_engine: PriorityEngine | None = None,
    ) -> dict[str, Any]:
        ranked = self.rank_goals(context=context, priority_engine=priority_engine)
        return {
            "generated_at": _utc_now().isoformat(),
            "total_goals": len(self._goals),
            "active_goals": len(self.list_goals(status="active")),
            "completed_goals": len(self.list_goals(status="completed")),
            "top_goal": ranked[0]["goal"] if ranked else None,
            "ranked_goals": [
                {
                    "goal": item["goal"],
                    "score": item["score"],
                    "reasons": item["reasons"],
                }
                for item in ranked
            ],
        }
