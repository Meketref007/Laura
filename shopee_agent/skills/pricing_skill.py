"""Protect Margin skill — adjusts prices to maintain minimum margin."""

from __future__ import annotations

from .registry import Skill, default_registry


class ProtectMarginSkill(Skill):
    name = "protect_margin"
    risk_level = "MEDIUM"
    preconditions = {}
    effects = {"margin_protected": True}
    cost = 1.5
    priority = 1

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def run(self, item_id: str = "", current_price: float = 0.0, min_margin_pct: float = 20.0, **kwargs) -> dict:
        """Suggest price adjustment to protect margin."""
        from shopee_agent.decision_engine import EconomicContext
        ctx = kwargs.get("context")
        margin = 0.0
        if isinstance(ctx, EconomicContext):
            margin = ctx.current_margin_pct
        elif isinstance(ctx, dict):
            margin = ctx.get("current_margin_pct", 0.0)

        if margin < min_margin_pct:
            return {
                "item_id": item_id,
                "action": "protect_margin",
                "current_margin_pct": margin,
                "min_margin_pct": min_margin_pct,
                "recommendation": f"Margem {margin:.1f}% abaixo de {min_margin_pct:.0f}% — ajustar preço",
                "suggested_increase_pct": round(min_margin_pct - margin + 2.0, 1),
            }
        return {
            "item_id": item_id,
            "action": "none",
            "current_margin_pct": margin,
            "min_margin_pct": min_margin_pct,
            "recommendation": "Margem OK",
        }


default_registry.register(ProtectMarginSkill)
