"""Low Stock Alert skill — warns when stock drops below threshold."""

from __future__ import annotations

from .registry import Skill, default_registry


class LowStockAlertSkill(Skill):
    name = "low_stock_alert"
    risk_level = "LOW"
    preconditions = {}
    effects = {"stock_checked": True}
    cost = 0.8
    priority = 2

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def run(self, item_id: str = "", stock: int = 0, threshold: int = 3, **kwargs) -> dict:
        """Check stock level and return alert if below threshold."""
        if not item_id:
            return {"error": "item_id required"}
        if stock <= 0:
            return {
                "item_id": item_id,
                "stock": stock,
                "alert": True,
                "message": f"Item {item_id} está sem estoque!",
            }
        if stock < threshold:
            return {
                "item_id": item_id,
                "stock": stock,
                "alert": True,
                "message": f"Item {item_id} tem apenas {stock} unidades (mínimo {threshold})",
            }
        return {"item_id": item_id, "stock": stock, "alert": False}


default_registry.register(LowStockAlertSkill)
