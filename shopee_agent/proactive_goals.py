"""Proactive Goals — suggests goals based on store metrics and planner state."""

from __future__ import annotations

from typing import Any


def suggest_goals(metrics: dict[str, Any], planner: Any = None) -> list[dict[str, Any]]:
    """Analyze store metrics and suggest goals the planner should pursue.

    Uses simple heuristic rules based on common Shopee scenarios.
    """
    suggestions: list[dict[str, Any]] = []
    margin = metrics.get("current_margin_pct", 100)
    target_margin = metrics.get("margin_target_pct", 30)
    stock_risk = metrics.get("stock_risk_level", "normal")
    orders_pending = metrics.get("orders_pending_ship", 0)
    support_pending = metrics.get("support_pending", 0)
    ad_roas = metrics.get("advertising_roas", 2.0)
    metrics.get("daily_revenue_usd", 0)
    inventory_days = metrics.get("inventory_days_on_hand", 30)
    cash_buffer = metrics.get("cash_buffer_usd", 1000)

    # Margin at risk
    if margin < target_margin * 0.8:
        suggestions.append({
            "goal": {"margin_protected": True},
            "priority": 10,
            "reason": f"Margem atual ({margin:.1f}%) está abaixo da meta ({target_margin}%)",
            "suggested_skills": ["protect_margin"],
        })

    # Stock critical
    if stock_risk == "critical":
        suggestions.append({
            "goal": {"stock_checked": True, "low_stock_restocked": True},
            "priority": 9,
            "reason": "Estoque em nível crítico",
            "suggested_skills": ["low_stock_alert", "create_purchase_order"],
        })

    # Pending orders
    if orders_pending > 0:
        suggestions.append({
            "goal": {"orders_pending_ship": False},
            "priority": 8,
            "reason": f"{orders_pending} pedido(s) aguardando expedição",
            "suggested_skills": ["order_ship"],
        })

    # Support pending
    if support_pending > 0:
        suggestions.append({
            "goal": {"support_handled": True},
            "priority": 7,
            "reason": f"{support_pending} mensagem(ns) de cliente sem resposta",
            "suggested_skills": ["auto_support"],
        })

    # Low ad ROAS
    if ad_roas < 1.0:
        suggestions.append({
            "goal": {"ads_optimized": True},
            "priority": 6,
            "reason": f"ROAS de anúncios baixo ({ad_roas:.1f})",
            "suggested_skills": ["analyze_ad_roas", "adjust_ad_budget"],
        })

    # Excess inventory
    if inventory_days > 90:
        suggestions.append({
            "goal": {"excess_cleared": True},
            "priority": 5,
            "reason": f"Estoque com {inventory_days} dias parados",
            "suggested_skills": ["clear_excess_stock"],
        })

    # Low cash buffer
    if cash_buffer < 500:
        suggestions.append({
            "goal": {"margin_protected": True},
            "priority": 9,
            "reason": f"Caixa baixo (${cash_buffer:.0f}) — proteger margem é crítico",
            "suggested_skills": ["protect_margin", "reduce_ad_spend"],
        })

    return suggestions
