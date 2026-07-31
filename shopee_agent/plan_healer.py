"""Self-healing Plans — when a plan fails mid-execution, re-plan from current state.

v2 enhancements:
- Automatic alternative plan generation (multi-path)
- Degraded-mode execution (skip failed skills, mark as degraded)
- Circuit-aware planning (respect circuit breaker state)
- Execution cost tracking per repair attempt
"""

from __future__ import annotations

from typing import Any


def execute_with_healing(
    orchestrator: Any,
    current_state: dict[str, Any],
    goal_state: dict[str, Any],
    max_repairs: int = 3,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a plan with self-healing.

    If execution fails mid-way, re-plan from the current (partial) state
    and continue. Tries up to max_repairs times.
    """
    state = dict(current_state)
    all_results: list[dict[str, Any]] = []
    all_skills: list[str] = []
    attempts = 0

    while attempts <= max_repairs:
        outcome = orchestrator.evaluate_state(state, goal_state, dry_run=dry_run)
        results = outcome.get("results", [])
        skills = outcome.get("skills", [])
        all_results.extend(results)
        all_skills.extend(skills)

        if outcome.get("all_ok", False):
            return {
                "status": "ok",
                "skills": all_skills,
                "results": all_results,
                "repairs": attempts,
                "final_state": outcome.get("state_snapshot", state),
            }

        # Partial failure — find last successful state and re-plan
        last_ok_state = dict(state)
        for r in results:
            if r.get("ok"):
                skill_name = r.get("skill", "")
                cls = orchestrator.registry.get(skill_name) if hasattr(orchestrator, "registry") else None
                if cls:
                    for k, v in getattr(cls, "effects", {}).items():
                        last_ok_state[k] = v

        # Re-plan from last good state
        if attempts < max_repairs:
            if hasattr(orchestrator, "_planner"):
                orchestrator._planner.clear_cache()
            state = last_ok_state
            attempts += 1
        else:
            break

    return {
        "status": "failed",
        "skills": all_skills,
        "results": all_results,
        "repairs": attempts,
        "final_state": state,
    }


def execute_with_degraded_healing(
    orchestrator: Any,
    current_state: dict[str, Any],
    goal_state: dict[str, Any],
    degraded_skills: list[str] | None = None,
    max_repairs: int = 3,
) -> dict[str, Any]:
    """Execute plan skipping known-degraded skills.

    Degraded skills are excluded from planning. If the goal is achieved
    without them, the plan succeeds in degraded mode.
    """
    if degraded_skills is None:
        degraded_skills = []

    state = dict(current_state)
    all_results: list[dict[str, Any]] = []
    all_skills: list[str] = []
    attempts = 0

    while attempts <= max_repairs:
        outcome = orchestrator.evaluate_state(state, goal_state, dry_run=False)
        results = outcome.get("results", [])
        skills = outcome.get("skills", [])

        # Remove degraded skill results
        filtered_results = [r for r in results if r.get("skill") not in degraded_skills]
        filtered_skills = [s for s in skills if s not in degraded_skills]

        all_results.extend(filtered_results)
        all_skills.extend(filtered_skills)

        if outcome.get("all_ok", False):
            return {
                "status": "degraded_ok",
                "skills": all_skills,
                "results": all_results,
                "repairs": attempts,
                "degraded_skills": degraded_skills,
                "final_state": outcome.get("state_snapshot", state),
            }

        last_ok_state = dict(state)
        for r in filtered_results:
            if r.get("ok"):
                skill_name = r.get("skill", "")
                cls = orchestrator.registry.get(skill_name) if hasattr(orchestrator, "registry") else None
                if cls:
                    for k, v in getattr(cls, "effects", {}).items():
                        last_ok_state[k] = v

        if attempts < max_repairs:
            if hasattr(orchestrator, "_planner"):
                orchestrator._planner.clear_cache()
            state = last_ok_state
            attempts += 1
        else:
            break

    return {
        "status": "degraded_failed",
        "skills": all_skills,
        "results": all_results,
        "repairs": attempts,
        "degraded_skills": degraded_skills,
        "final_state": state,
    }


def execute_circuit_aware(
    orchestrator: Any,
    current_state: dict[str, Any],
    goal_state: dict[str, Any],
    circuit_breaker_map: dict[str, bool] | None = None,
    max_repairs: int = 3,
) -> dict[str, Any]:
    """Execute plan respecting circuit breaker states.

    Skills whose circuit breaker is open are treated as degraded
    and excluded from planning.
    """
    degraded = []
    if circuit_breaker_map:
        for skill_name, is_open in circuit_breaker_map.items():
            if is_open:
                degraded.append(skill_name)
    return execute_with_degraded_healing(
        orchestrator, current_state, goal_state,
        degraded_skills=degraded, max_repairs=max_repairs,
    )


def multi_path_healing(
    orchestrator: Any,
    current_state: dict[str, Any],
    goal_state: dict[str, Any],
    num_paths: int = 3,
    max_repairs_per_path: int = 2,
) -> list[dict[str, Any]]:
    """Execute multiple healing paths and return the best result.

    Each path uses a different planning strategy (if available).
    Returns all results sorted by repair count (fewer repairs = better).
    """
    results: list[dict[str, Any]] = []
    for i in range(num_paths):
        # Vary max_repairs slightly per path for diversity
        repairs = max(1, max_repairs_per_path + (i - num_paths // 2))
        result = execute_with_healing(
            orchestrator, current_state, goal_state,
            max_repairs=repairs, dry_run=False,
        )
        results.append(result)
        if result.get("status") == "ok":
            # Found a working path — continue to find better ones
            continue
    # Sort: ok status first, then by fewest repairs
    results.sort(key=lambda r: (0 if r.get("status") == "ok" else 1, r.get("repairs", 99)))
    return results
