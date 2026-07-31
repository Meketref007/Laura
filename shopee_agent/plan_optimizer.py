"""Plan Optimizer — uses learning data to suggest better plans and detect inefficiencies."""

from __future__ import annotations

from typing import Any


def suggest_optimizations(planner: Any) -> list[dict[str, Any]]:
    """Analyze planner learning data and suggest optimizations."""
    suggestions: list[dict[str, Any]] = []
    summary = planner.get_learning_summary()
    overrides = summary.get("cost_overrides", {})

    if not overrides:
        return suggestions

    base_actions = summary.get("base_actions", [])

    # Find skills with high cost drift (learned cost much higher than base)
    for action_name in base_actions:
        stats = planner.get_learning_stats(action_name)
        current_cost = stats.get("current_cost", 1.0)
        executions = stats.get("executions", 0)
        success_rate = stats.get("success_rate", 0.0)
        next(
            (float(v) for k, v in (overrides.items() if isinstance(overrides, dict) else []) if k == action_name),
            None,
        )

        # If success rate is very low, suggest investigation
        if executions >= 3 and success_rate < 0.3:
            suggestions.append({
                "type": "low_success_rate",
                "skill": action_name,
                "detail": f"Success rate is only {success_rate:.0%} after {executions} executions",
                "severity": "high",
            })

        # If cost has drifted significantly (>2x base), suggest investigation
        if executions >= 5 and current_cost > 2.0:
            suggestions.append({
                "type": "cost_drift",
                "skill": action_name,
                "detail": f"Cost has drifted to {current_cost:.2f} (may indicate inefficiency)",
                "severity": "medium",
            })

    # Suggest alternative action ordering based on success rates
    if len(base_actions) >= 2:
        suggestions.append({
            "type": "info",
            "skill": "system",
            "detail": f"{len(base_actions)} skills registered. Run 'laura skill-simulate' to test alternative orderings.",
            "severity": "low",
        })

    return suggestions


def compare_plan_costs(planner: Any, state: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    """Compare costs of different plan approaches to achieve the same goal."""
    plan = planner.plan(state, goal, use_cache=False)
    if plan is None:
        return {"status": "no_plan", "recommendation": None}

    primary_cost = sum(a.cost for a in plan)
    primary_actions = [a.name for a in plan]

    # Find cheaper alternative: try removing the most expensive action
    if len(plan) > 1:
        most_expensive = max(plan, key=lambda a: a.cost)
        saved_actions = [a for a in planner._actions if a.name != most_expensive.name]
        saved_actions_orig = planner._actions
        planner._actions = saved_actions
        alt_plan = planner.plan(state, goal, use_cache=False)
        planner._actions = saved_actions_orig

        if alt_plan is not None:
            alt_cost = sum(a.cost for a in alt_plan)
            alt_actions = [a.name for a in alt_plan]
            if alt_cost < primary_cost:
                return {
                    "status": "alternative_found",
                    "current_plan": {"actions": primary_actions, "total_cost": primary_cost},
                    "suggested_plan": {"actions": alt_actions, "total_cost": alt_cost},
                    "savings": round(primary_cost - alt_cost, 2),
                    "recommendation": f"Try plan without '{most_expensive.name}' to save {primary_cost - alt_cost:.1f} cost",
                }

    return {
        "status": "optimal",
        "current_plan": {"actions": primary_actions, "total_cost": primary_cost},
        "recommendation": "Current plan appears optimal",
    }
