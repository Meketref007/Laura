"""Plan Cost Prediction — predicts plan cost using historical learning data.

Uses simple statistical model: weighted average of recent costs per action.
"""

from __future__ import annotations

from typing import Any


def predict_cost(planner: Any, actions: list[str]) -> dict[str, Any]:
    """Predict total cost of a plan based on historical learning data.

    Returns predicted cost per action and total, with confidence score.
    """
    total_predicted = 0.0
    details: list[dict[str, Any]] = []
    base_total = 0.0
    high_uncertainty: list[str] = []

    for action_name in actions:
        stats = planner.get_learning_stats(action_name)
        current_cost = stats.get("current_cost", 1.0)
        executions = stats.get("executions", 0)
        base_cost = stats.get("base_cost", 1.0)

        # Predicted cost: blend learned cost with base cost based on confidence
        if executions >= 10:
            weight = 0.9  # high confidence in learned cost
            confidence = "high"
        elif executions >= 3:
            weight = 0.6
            confidence = "medium"
        else:
            weight = 0.3
            confidence = "low"
            high_uncertainty.append(action_name)

        predicted = base_cost * (1 - weight) + current_cost * weight
        total_predicted += predicted
        base_total += base_cost

        details.append({
            "action": action_name,
            "base_cost": base_cost,
            "learned_cost": current_cost,
            "predicted_cost": round(predicted, 2),
            "executions": executions,
            "confidence": confidence,
        })

    overall_confidence = "high" if not high_uncertainty else ("medium" if len(high_uncertainty) <= len(actions) / 2 else "low")

    return {
        "actions": details,
        "total_predicted": round(total_predicted, 2),
        "total_base": round(base_total, 2),
        "num_actions": len(actions),
        "high_uncertainty_actions": high_uncertainty,
        "confidence": overall_confidence,
    }
