"""Dynamic goal synthesis — infers GOAP goal states from KPIs and business context."""

from __future__ import annotations

from typing import Any

GOAL_TEMPLATES: dict[str, dict[str, Any]] = {
    "protect_margin": {"margin_protected": True},
    "scale_winners": {"winners_scaled": True},
    "reduce_loss": {"losses_reduced": True},
    "restock": {"stock_checked": True},
    "support_triage": {"support_handled": True},
    "price_optimize": {"prices_optimized": True},
    "full_audit": {"margin_protected": True, "stock_checked": True, "prices_optimized": True},
}


def synthesize_goal(
    margin_pct: float | None = None,
    low_margin_count: int = 0,
    low_stock_count: int = 0,
    refund_rate_pct: float = 0.0,
    profit: float | None = None,
    revenue: float | None = None,
    active_promos: int = 0,
    health_status: str = "HEALTHY",
) -> dict[str, Any]:
    """Infer a GOAP goal state from business KPIs.

    Returns a goal dict suitable for GOAPPlanner.plan().
    """
    goals: dict[str, Any] = {}

    # Margin protection
    if margin_pct is not None and margin_pct < 20:
        goals["margin_protected"] = True
    if low_margin_count > 0:
        goals["margin_protected"] = True

    # Stock / inventory
    if low_stock_count > 0:
        goals["stock_checked"] = True

    # Loss reduction
    if refund_rate_pct >= 5.0 or (profit is not None and profit < 0):
        goals["losses_reduced"] = True

    # Pricing
    if margin_pct is not None and margin_pct < 25:
        goals["prices_optimized"] = True

    # Support
    if health_status not in ("HEALTHY", "OK", "GOOD"):
        goals["support_handled"] = True

    # Default fallback
    if not goals:
        goals["monitor_ok"] = True

    return goals


def describe_goal(goal: dict[str, Any]) -> str:
    """Human-readable description of a goal state."""
    labels = {
        "margin_protected": "Proteger margem",
        "stock_checked": "Verificar estoque",
        "losses_reduced": "Reduzir perdas",
        "prices_optimized": "Otimizar precos",
        "support_handled": "Atender suporte",
        "monitor_ok": "Monitoramento normal",
    }
    parts = [labels.get(k, k) for k in goal]
    return " + ".join(parts) if parts else "Monitoramento normal"


def synthesize_goals_batch(kpi_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Synthesize goals for multiple KPI snapshots (e.g., per store)."""
    return [synthesize_goal(**{k: v for k, v in snap.items() if k in (
        "margin_pct", "low_margin_count", "low_stock_count", "refund_rate_pct",
        "profit", "revenue", "active_promos", "health_status",
    )}) for snap in kpi_snapshots]
