"""Shopee API sandbox integration — test skills against Shopee sandbox environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests as _requests

_SHOPEE_SANDBOX_BASE = "https://partner.test-stable.shopeemobile.com"


@dataclass
class SandboxResponse:
    ok: bool = False
    data: Any = None
    error: str = ""
    status_code: int = 0


class ShopeeSandboxClient:
    """Minimal client for Shopee's sandbox API environment.

    Uses the same partner_id/partner_key as production but targets
    the sandbox base URL.
    """

    def __init__(
        self,
        partner_id: int | None = None,
        partner_key: str | None = None,
        base_url: str = _SHOPEE_SANDBOX_BASE,
    ):
        self.partner_id = partner_id or int(os.getenv("SHOPEE_PARTNER_ID", "0"))
        self.partner_key = partner_key or os.getenv("SHOPEE_PARTNER_KEY", "")
        self.base_url = base_url

    def _sign(self, path: str, timestamp: int) -> str:
        import hashlib
        import hmac
        base = f"{self.partner_id}{path}{timestamp}"
        return hmac.new(self.partner_key.encode(), base.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> SandboxResponse:
        import time
        timestamp = int(time.time())
        params = dict(params or {})
        params["partner_id"] = self.partner_id
        params["timestamp"] = timestamp
        params["sign"] = self._sign(path, timestamp)

        url = urljoin(self.base_url, path)
        try:
            if method == "GET":
                resp = _requests.get(url, params=params, timeout=15)
            else:
                resp = _requests.post(url, json=params, timeout=15)
            data = resp.json()
            if resp.status_code == 200 and data.get("error") == 0:
                return SandboxResponse(ok=True, data=data, status_code=resp.status_code)
            return SandboxResponse(ok=False, data=data, error=data.get("message", "unknown"), status_code=resp.status_code)
        except Exception as exc:
            return SandboxResponse(ok=False, error=str(exc))

    def get_item_list(self, shop_id: int, access_token: str, offset: int = 0, page_size: int = 50) -> SandboxResponse:
        return self._request("GET", "/api/v2/product/item_list", {
            "shop_id": shop_id,
            "access_token": access_token,
            "offset": offset,
            "page_size": page_size,
        })

    def get_item_detail(self, shop_id: int, access_token: str, item_id: int) -> SandboxResponse:
        return self._request("GET", "/api/v2/product/item_detail", {
            "shop_id": shop_id,
            "access_token": access_token,
            "item_id": item_id,
        })

    def update_price(self, shop_id: int, access_token: str, item_id: int, price: float) -> SandboxResponse:
        return self._request("POST", "/api/v2/product/price", {
            "shop_id": shop_id,
            "access_token": access_token,
            "item_id": [item_id],
            "price": [price],
        })

    def update_stock(self, shop_id: int, access_token: str, item_id: int, stock: int) -> SandboxResponse:
        return self._request("POST", "/api/v2/product/stock", {
            "shop_id": shop_id,
            "access_token": access_token,
            "item_id": item_id,
            "stock": stock,
        })

    def get_orders(self, shop_id: int, access_token: str, order_status: str = "READY_TO_SHIP", page_size: int = 50) -> SandboxResponse:
        return self._request("GET", "/api/v2/order/get_order_list", {
            "shop_id": shop_id,
            "access_token": access_token,
            "order_status": order_status,
            "page_size": page_size,
        })

    def test_connectivity(self) -> dict[str, Any]:
        return {"reachable": self.health_check(), "sandbox_url": self.base_url}

    def health_check(self) -> bool:
        """Simple connectivity test."""
        resp = self._request("GET", "/api/v2/shop/get_shop_info", {"shop_id": 0, "access_token": ""})
        return not resp.ok  # expected to fail without valid creds — means endpoint is reachable


class SandboxSkillTester:
    """Runs skills against the sandbox and reports results."""

    def __init__(self, client: ShopeeSandboxClient | None = None):
        self.client = client or ShopeeSandboxClient()

    def test_skill(self, skill_name: str, skill_fn: Any, **kwargs: Any) -> dict[str, Any]:
        """Run a skill function against the sandbox.

        Returns a dict with ok/result/error and sandbox_response.
        """
        try:
            result = skill_fn(**kwargs)
            return {"ok": True, "result": str(result)[:500], "sandbox": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sandbox": True}

    def test_connectivity(self) -> dict[str, Any]:
        return {"reachable": self.client.health_check(), "sandbox_url": self.client.base_url}
