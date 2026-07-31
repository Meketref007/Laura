"""Plan Conformance — after execution, verify actual effects match expected plan effects."""

from __future__ import annotations

from typing import Any


def check_conformance(
    expected_actions: list[str],
    expected_effects: dict[str, Any],
    actual_results: list[dict[str, Any]],
    actual_state: dict[str, Any],
    registry: Any,
) -> dict[str, Any]:
    """Verify that the actual execution matches the planned effects.

    Returns conformance report with matched, missing, and unexpected effects.
    """
    # Collect expected effects from each action
    planned_effects: dict[str, Any] = {}
    for skill_name in expected_actions:
        cls = registry.get(skill_name)
        if cls:
            planned_effects.update(getattr(cls, "effects", {}))

    # Check which expected effects were actually achieved
    matched: dict[str, Any] = {}
    missing: dict[str, Any] = {}
    for k, expected_v in planned_effects.items():
        actual_v = actual_state.get(k)
        if actual_v == expected_v:
            matched[k] = actual_v
        else:
            missing[k] = {"expected": expected_v, "actual": actual_v}

    # Check for unexpected state changes (effects not in plan)
    unexpected: dict[str, Any] = {}
    for k, actual_v in actual_state.items():
        if k not in planned_effects and k not in expected_effects:
            unexpected[k] = actual_v

    # Check which skills actually executed successfully
    executed = [r.get("skill", "") for r in actual_results if r.get("ok")]
    failed = [r.get("skill", "") for r in actual_results if not r.get("ok")]
    not_executed = [s for s in expected_actions if s not in executed and s not in failed]

    conformance_pct = (len(matched) / len(planned_effects) * 100) if planned_effects else 100.0

    return {
        "status": "conformant" if conformance_pct >= 80 else "non_conformant",
        "conformance_pct": round(conformance_pct, 1),
        "effects_planned": len(planned_effects),
        "effects_matched": len(matched),
        "effects_missing": len(missing),
        "effects_unexpected": len(unexpected),
        "matched": matched,
        "missing": missing,
        "unexpected": unexpected,
        "executed_skills": executed,
        "failed_skills": failed,
        "not_executed": not_executed,
        "goal_achieved": all(actual_state.get(k) == v for k, v in expected_effects.items()),
    }
