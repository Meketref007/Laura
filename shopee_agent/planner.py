from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .strategic_planner import Goal, StrategicPlan


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class PlanTask:
    task_id: str
    name: str
    action: str
    dependencies: list[str] = field(default_factory=list)
    retries: int = 0
    rollback_action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskExecution:
    task_id: str
    status: str
    attempts: int
    result: Any = None
    error: str | None = None
    rolled_back: bool = False
    rollback_result: Any = None
    started_at: str = field(default_factory=lambda: _utc_now().isoformat())
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanExecution:
    plan_id: str
    status: str
    task_results: list[TaskExecution] = field(default_factory=list)
    ordered_task_ids: list[str] = field(default_factory=list)
    failed_task_id: str | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status,
            "task_results": [result.to_dict() for result in self.task_results],
            "ordered_task_ids": list(self.ordered_task_ids),
            "failed_task_id": self.failed_task_id,
            "summary": self.summary,
        }


class Planner:
    """Small DAG planner with retries and rollback support."""

    def build_plan_from_goal(self, goal: Goal) -> list[PlanTask]:
        objective = goal.objective.lower()
        base = goal.name.lower().replace(" ", "_")

        if any(token in objective for token in {"margin", "profit", "profitability"}):
            return [
                PlanTask(f"{base}_diagnose", "diagnose margin drivers", "analyze_margin", retries=1),
                PlanTask(
                    f"{base}_protect",
                    "protect margin",
                    "raise_prices_or_reduce_spend",
                    dependencies=[f"{base}_diagnose"],
                    retries=2,
                    rollback_action="restore_previous_price_and_budget",
                ),
                PlanTask(
                    f"{base}_stabilize",
                    "stabilize results",
                    "monitor_margin_trend",
                    dependencies=[f"{base}_protect"],
                ),
            ]

        if any(token in objective for token in {"roas", "ads", "spend"}):
            return [
                PlanTask(f"{base}_audit", "audit campaigns", "inspect_ads_performance", retries=1),
                PlanTask(
                    f"{base}_reallocate",
                    "reallocate budget",
                    "shift_budget_to_winners",
                    dependencies=[f"{base}_audit"],
                    retries=2,
                    rollback_action="restore_previous_budget_split",
                ),
                PlanTask(
                    f"{base}_scale",
                    "scale winners",
                    "expand_top_ads",
                    dependencies=[f"{base}_reallocate"],
                ),
            ]

        return [
            PlanTask(f"{base}_discover", "discover current state", "map_constraints", retries=1),
            PlanTask(f"{base}_execute", "execute core steps", "run_primary_actions", dependencies=[f"{base}_discover"], retries=1),
            PlanTask(f"{base}_review", "review and adjust", "review_outcomes", dependencies=[f"{base}_execute"]),
        ]

    def build_plan_from_strategic_plan(self, plan: StrategicPlan) -> list[PlanTask]:
        tasks: list[PlanTask] = []
        for phase in plan.phases:
            dependencies = list(phase.dependencies)
            tasks.append(
                PlanTask(
                    task_id=phase.phase_id,
                    name=phase.name,
                    action="; ".join(phase.actions),
                    dependencies=dependencies,
                    retries=1,
                    rollback_action="rollback_phase" if phase.gates else None,
                    metadata={"owner": phase.owner, "gates": [gate.name for gate in phase.gates]},
                )
            )
        return tasks

    def execute(
        self,
        tasks: list[PlanTask],
        runner: Callable[[PlanTask], Any],
        rollback_runner: Callable[[PlanTask], Any] | None = None,
    ) -> PlanExecution:
        ordered = self._topological_sort(tasks)
        task_map = {task.task_id: task for task in tasks}
        results: list[TaskExecution] = []
        completed: set[str] = set()

        for task_id in ordered:
            task = task_map[task_id]
            attempts = 0
            last_error: str | None = None
            result_value: Any = None
            status = "completed"

            while attempts <= task.retries:
                attempts += 1
                try:
                    result_value = runner(task)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = str(exc)
                    status = "failed"
                    if attempts > task.retries:
                        break

            finished_at = _utc_now().isoformat()
            execution = TaskExecution(
                task_id=task.task_id,
                status=status if last_error else "completed",
                attempts=attempts,
                result=result_value,
                error=last_error,
                finished_at=finished_at,
            )

            if last_error:
                if rollback_runner is not None and task.rollback_action is not None:
                    try:
                        execution.rollback_result = rollback_runner(task)
                        execution.rolled_back = True
                    except Exception as rollback_exc:
                        execution.rollback_result = str(rollback_exc)
                results.append(execution)
                return PlanExecution(
                    plan_id=f"plan_{ordered[0][:8] if ordered else 'empty'}",
                    status="failed",
                    task_results=results,
                    ordered_task_ids=ordered,
                    failed_task_id=task.task_id,
                    summary=f"Task {task.task_id} failed after {attempts} attempt(s)",
                )

            results.append(execution)
            completed.add(task.task_id)

        return PlanExecution(
            plan_id=f"plan_{ordered[0][:8] if ordered else 'empty'}",
            status="completed",
            task_results=results,
            ordered_task_ids=ordered,
            summary=f"Executed {len(results)} task(s) successfully",
        )

    def _topological_sort(self, tasks: list[PlanTask]) -> list[str]:
        task_ids = {task.task_id for task in tasks}
        task_map = {task.task_id: task for task in tasks}
        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise RuntimeError(f"circular task dependency detected: {task_id}")
            visiting.add(task_id)
            for dependency in task_map[task_id].dependencies:
                if dependency in task_ids:
                    visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)
            ordered.append(task_id)

        for task in tasks:
            visit(task.task_id)

        return ordered
