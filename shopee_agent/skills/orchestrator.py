"""SkillOrchestrator — uses GOAP to decide which skills to run."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.event_bus import GOAPPlanExecutedEvent
from shopee_agent.goap_planner import GOAPAgent, GOAPPlanner, MultiAgentGOAP
from shopee_agent.logger import info, warning
from shopee_agent.paths import GOAP_LEARNING, SKILL_EXECUTION_HISTORY
from shopee_agent.plan_store import PlanStore
from shopee_agent.skills.registry import _resolve_dag, default_registry
from shopee_agent.skills.sandbox import run_skill_sandbox
from shopee_agent.skills.state_store import GOAPStateStore


class SkillOrchestrator:
    """Uses GOAP A* search to select the best sequence of skills for a goal.

    Supports:
    - Priority-based action ordering (critical skills first)
    - Parallel execution of non-conflicting skills
    - Skill composition (sub-skills expanded recursively)
    - Sandbox execution (dry-run, timeout, circuit breaker, rate limiter, retry)
    - Learning feedback (cost adjustment on success/failure)
    - Event emission for observability
    - State persistence with diff/merge across cycles
    - Compensation/rollback on plan failure
    - Plan cache (avoids re-planning when state unchanged)
    - Multi-agent GOAP (multiple planners with conflict resolution)
    """

    def __init__(
        self,
        registry: Any = None,
        history_path: str = str(SKILL_EXECUTION_HISTORY),
        learning_path: str = str(GOAP_LEARNING),
        event_bus: Any | None = None,
    ):
        self.registry = registry or default_registry
        self._planner = GOAPPlanner(learning_path=learning_path)
        self._planner._skill_registry = self.registry
        self._planner.load_skills(self.registry)
        self._history_path = Path(history_path)
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus
        self._state_store = GOAPStateStore()
        self._multi_agent = MultiAgentGOAP()
        self._plan_store = PlanStore()

    def add_goap_agent(self, name: str, planner: GOAPPlanner, priority: int = 0) -> None:
        self._multi_agent.add_agent(GOAPAgent(name=name, planner=planner, priority=priority))

    # ── Plan computation ──────────────────────────────────────────────────

    def determine_skills(
        self,
        current_state: dict[str, Any],
        goal_state: dict[str, Any],
        max_depth: int = 6,
        prioritize_critical: bool = True,
        use_cache: bool = True,
        max_budget: float | None = None,
    ) -> list[str]:
        """Return ordered skill names to reach goal_state from current_state."""
        plan = self._planner.plan(current_state, goal_state, max_depth=max_depth, use_cache=use_cache, max_budget=max_budget)
        if plan is None:
            return []
        names = [a.name for a in plan]
        # Expand sub-skills recursively
        expanded = self._expand_sub_skills(names)
        # DAG topological sort by dependencies
        expanded = _resolve_dag(expanded, self.registry)
        if prioritize_critical and expanded:
            order = {n: i for i, n in enumerate(expanded)}
            skill_meta = {}
            for name in expanded:
                cls = self.registry.get(name)
                prio = getattr(cls, "priority", 0) if cls else 0
                skill_meta[name] = prio
            expanded.sort(key=lambda n: (-skill_meta.get(n, 0), order.get(n, 0)))
        return expanded

    def _expand_sub_skills(self, names: list[str], _depth: int = 0) -> list[str]:
        if _depth > 5:
            return names
        result: list[str] = []
        for name in names:
            result.append(name)
            cls = self.registry.get(name)
            if cls is None:
                continue
            subs = list(getattr(cls, "sub_skills", []))
            if subs:
                result.extend(self._expand_sub_skills(subs, _depth + 1))
        return result

    def determine_parallel_batches(self, skill_names: list[str]) -> list[list[str]]:
        """Group skills into parallel execution batches."""
        return self._planner.group_independent(skill_names)

    # ── Execution ─────────────────────────────────────────────────────────

    async def execute_plan_async(
        self,
        skill_names: list[str],
        context: dict[str, Any] | None = None,
        dry_run: bool = False,
        timeout_seconds: float = 30.0,
        compensate_on_failure: bool = True,
        parallel: bool = False,
        max_retries: int = 0,
        retry_base_delay: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Execute a list of skills by name with sandbox protections.

        If parallel=True, non-conflicting skills run concurrently in batches.
        """
        if parallel:
            batches = self.determine_parallel_batches(skill_names)
        else:
            batches = [[n] for n in skill_names]

        results: list[dict[str, Any]] = []
        succeeded_names: list[str] = []

        for batch in batches:
            if len(batch) == 1:
                result = await self._execute_single(
                    batch[0], context or {}, dry_run, timeout_seconds, max_retries, retry_base_delay,
                )
                results.append(result)
                if result["ok"]:
                    succeeded_names.append(batch[0])
                else:
                    if compensate_on_failure:
                        self._compensate(succeeded_names, context or {})
                    break
            else:
                batch_results = await asyncio.gather(*[
                    self._execute_single(name, context or {}, dry_run, timeout_seconds, max_retries, retry_base_delay)
                    for name in batch
                ])
                results.extend(batch_results)
                for br in batch_results:
                    if br["ok"]:
                        succeeded_names.append(br["skill"])
                    else:
                        if compensate_on_failure:
                            self._compensate(succeeded_names, context or {})
                        break
                # If any in batch failed, stop
                if not all(br["ok"] for br in batch_results):
                    break

        return results

    async def _execute_single(
        self, name: str, context: dict[str, Any], dry_run: bool,
        timeout_seconds: float, max_retries: int, retry_base_delay: float,
    ) -> dict[str, Any]:
        skill = self.registry.get_or_create(name)
        if skill is None:
            return {"skill": name, "ok": False, "error": "not_found"}
        result = await run_skill_sandbox(
            skill_name=name,
            run_fn=skill.run,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            **(context),
        )
        result["skill"] = name
        self._append_history(name, ok=result["ok"], result=str(result.get("result", "")), error=str(result.get("error", "")))
        if result["ok"]:
            self._planner.record_outcome(name, success=True)
        else:
            self._planner.record_outcome(name, success=False)
        return result

    def _compensate(self, succeeded_names: list[str], context: dict[str, Any]) -> None:
        """Rollback succeeded skills by running their reverse skills."""
        for name in reversed(succeeded_names):
            cls = self.registry.get(name)
            if cls is None:
                continue
            rev_name = getattr(cls, "reverse_name", "")
            if not rev_name:
                continue
            rev_cls = self.registry.get(rev_name)
            if rev_cls is None:
                continue
            try:
                rev_skill = rev_cls()
                rev_result = asyncio.run(run_skill_sandbox(rev_name, rev_skill.run, **context))
                info(f"Compensation: reversed '{name}' via '{rev_name}': ok={rev_result.get('ok')}")
            except Exception as exc:
                warning(f"Compensation failed for '{name}' via '{rev_name}': {exc}")

    def execute_plan(
        self,
        skill_names: list[str],
        context: dict[str, Any] | None = None,
        dry_run: bool = False,
        timeout_seconds: float = 30.0,
        compensate_on_failure: bool = True,
        parallel: bool = False,
        max_retries: int = 0,
        retry_base_delay: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Synchronous wrapper for execute_plan_async."""
        return asyncio.run(self.execute_plan_async(
            skill_names, context=context, dry_run=dry_run,
            timeout_seconds=timeout_seconds, compensate_on_failure=compensate_on_failure,
            parallel=parallel, max_retries=max_retries, retry_base_delay=retry_base_delay,
        ))

    def evaluate_state(
        self,
        current_state: dict[str, Any],
        goal_state: dict[str, Any],
        max_depth: int = 6,
        dry_run: bool = False,
        timeout_seconds: float = 30.0,
        prioritize_critical: bool = True,
        compensate_on_failure: bool = True,
        parallel: bool = False,
        max_retries: int = 0,
        retry_base_delay: float = 1.0,
        use_cache: bool = True,
        max_budget: float | None = None,
    ) -> dict[str, Any]:
        """Determine + execute skills for a given state transition."""
        skills = self.determine_skills(
            current_state, goal_state, max_depth=max_depth,
            prioritize_critical=prioritize_critical, use_cache=use_cache, max_budget=max_budget,
        )
        if not skills:
            return {"status": "no_plan", "skills": [], "results": []}
        results = self.execute_plan(
            skills, context=current_state, dry_run=dry_run,
            timeout_seconds=timeout_seconds, compensate_on_failure=compensate_on_failure,
            parallel=parallel, max_retries=max_retries, retry_base_delay=retry_base_delay,
        )
        all_ok = all(r["ok"] for r in results)
        total_cost = sum(
            getattr(self.registry.get(r["skill"]), "cost", 1.0) for r in results if self.registry.get(r["skill"])
        )
        # Persist plan to PlanStore
        plan_hash = hashlib.md5(
            json.dumps(current_state, sort_keys=True).encode()
            + json.dumps(goal_state, sort_keys=True).encode()
        ).hexdigest()
        plan_id = self._plan_store.save_plan(
            plan_hash, current_state, goal_state, skills, total_cost,
            max_depth=max_depth, max_budget=max_budget, all_ok=all_ok,
        )
        outcome = {
            "status": "executed" if not dry_run else "dry_run",
            "skills": skills,
            "results": results,
            "all_ok": all_ok,
            "total_cost": total_cost,
        }
        if plan_id:
            outcome["plan_id"] = plan_id
        self._emit_event(outcome, current_state)
        if not dry_run:
            self._persist_state(current_state, skills, all_ok)
        return outcome

    # ── Multi-agent ───────────────────────────────────────────────────────

    def evaluate_multi_agent(
        self,
        current_state: dict[str, Any],
        goal_map: dict[str, dict[str, Any]],
        max_depth: int = 6,
        dry_run: bool = False,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """Evaluate multiple agents with potentially conflicting goals."""
        multi_result = self._multi_agent.resolve(current_state, goal_map, max_depth=max_depth)
        merged_skills = multi_result.get("merged_actions", [])
        if not merged_skills:
            return {"status": "no_plan", "skills": [], "agents": multi_result.get("agents", {})}
        results = self.execute_plan(
            merged_skills, context=current_state, dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )
        return {
            "status": "executed" if not dry_run else "dry_run",
            "skills": merged_skills,
            "results": results,
            "agents": multi_result.get("agents", {}),
        }

    # ── State persistence ─────────────────────────────────────────────────

    def _persist_state(self, state: dict[str, Any], skills: list[str], all_ok: bool) -> None:
        persisted = self._state_store.load()
        for name in skills:
            cls = self.registry.get(name)
            if cls is None:
                continue
            for k, v in getattr(cls, "effects", {}).items():
                persisted[k] = v
        persisted["_last_plan_ok"] = all_ok
        persisted["_last_plan_skills"] = skills
        persisted["_last_run"] = datetime.now(UTC).isoformat()
        for k in ("margin_pct", "daily_revenue", "stock_risk", "active_promos"):
            if k in state:
                persisted[k] = state[k]
        self._state_store.save(persisted)

    def load_persisted_state(self) -> dict[str, Any]:
        return self._state_store.load()

    def persist_with_diff(self, new_state: dict[str, Any]) -> dict[str, Any]:
        """Save state and return diff."""
        return self._state_store.save_with_diff(new_state)

    # ── Events ────────────────────────────────────────────────────────────

    def _emit_event(self, outcome: dict[str, Any], state: dict[str, Any]) -> None:
        bus = self.event_bus
        if bus is None:
            return
        try:
            ev = GOAPPlanExecutedEvent(
                actions=outcome.get("skills", []),
                total_cost=outcome.get("total_cost", 0.0),
                results=outcome.get("results", []),
                all_ok=outcome.get("all_ok", False),
                state_snapshot=state,
            )
            bus.submit(ev)
        except Exception as exc:
            warning("SkillOrchestrator failed to emit event", error=str(exc))

    def _append_history(
        self, skill_name: str, ok: bool, result: str = "", error: str = ""
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "skill": skill_name,
            "ok": ok,
            "result": result[:200],
            "error": error[:200],
        }
        try:
            with self._history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_learning_summary(self) -> dict[str, Any]:
        return self._planner.get_learning_summary()
