"""Order Ship skill — auto ship READY_TO_SHIP orders."""

from __future__ import annotations

from .registry import Skill, default_registry


class OrderShipSkill(Skill):
    name = "order_ship"
    risk_level = "HIGH"
    preconditions = {"orders_pending_ship": True}
    effects = {"orders_pending_ship": False}
    cost = 2.5
    priority = 3
    reverse_name = ""  # shipping cannot be reversed via API

    def __init__(self, client=None, **kwargs):
        super().__init__(**kwargs)
        self._client = client

    def run(self, order_sn: str = "", **kwargs) -> dict:
        """Ship a READY_TO_SHIP order via Shopee API."""
        client = self._client or self._get_client()
        if not client:
            return {"error": "No ShopeeClient available", "order_sn": order_sn}
        try:
            resp = client.ship_order(order_sn)
            return {"order_sn": order_sn, "shipped": True, "response": str(resp)[:200]}
        except Exception as e:
            return {"order_sn": order_sn, "shipped": False, "error": str(e)}

    @staticmethod
    def _get_client():
        try:
            from shopee_agent.client import ShopeeClient
            from shopee_agent.config import load_config
            cfg = load_config()
            return ShopeeClient(cfg)
        except Exception:
            return None


default_registry.register(OrderShipSkill)
