"""
seller_center.py - Access to Shopee Seller Center (Central do Vendedor)
via browser cookies for data and actions not available through the Open API.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from shopee_agent.logger import error, info, warning
from shopee_agent.paths import SELLER_CENTER_COOKIES

SELLER_CENTER_BASE = "https://seller.shopee.com.br"
SHOPEE_BASE = "https://shopee.com.br"
COOKIES_FILE = str(SELLER_CENTER_COOKIES)


@dataclass
class SellerCenterCookie:
    domain: str
    name: str
    value: str
    path: str = "/"
    secure: bool = True
    httpOnly: bool = False
    expirationDate: float | None = None
    hostOnly: bool = False
    sameSite: str | None = None
    session: bool = False

    def is_expired(self) -> bool:
        if self.expirationDate is None:
            return False
        return time.time() > self.expirationDate

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SellerCenterCookie:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class SellerCenterSession:
    cookies: list[SellerCenterCookie] = field(default_factory=list)
    saved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    shop_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cookies": [c.to_dict() for c in self.cookies],
            "saved_at": self.saved_at,
            "shop_id": self.shop_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SellerCenterSession:
        cookies = [SellerCenterCookie.from_dict(c) for c in data.get("cookies", [])]
        return cls(
            cookies=cookies,
            saved_at=data.get("saved_at", ""),
            shop_id=data.get("shop_id"),
        )

    def get_cookie(self, name: str) -> SellerCenterCookie | None:
        for c in self.cookies:
            if c.name == name:
                return c
        return None

    def get_requests_session(self) -> requests.Session:
        session = requests.Session()
        for c in self.cookies:
            if c.is_expired():
                continue
            session.cookies.set(
                c.name,
                c.value,
                domain=c.domain,
                path=c.path,
                secure=c.secure,
            )
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Origin": SELLER_CENTER_BASE,
            "Referer": f"{SELLER_CENTER_BASE}/",
        })
        return session

    def is_valid(self) -> bool:
        if not self.cookies:
            return False
        required = ["SPC_SI", "SPC_ST", "SPC_EC"]
        for name in required:
            c = self.get_cookie(name)
            if c is None or c.is_expired():
                return False
        return True


def load_cookies(path: str = COOKIES_FILE) -> SellerCenterSession | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return SellerCenterSession.from_dict(data)
    except Exception as e:
        warning(f"Failed to load seller center cookies: {e}")
        return None


def save_cookies(session: SellerCenterSession, path: str = COOKIES_FILE) -> bool:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        info(f"Seller center cookies saved to {path}")
        return True
    except Exception as e:
        error(f"Failed to save seller center cookies: {e}")
        return False


def import_from_browser(cookie_json: str, shop_id: str | None = None) -> SellerCenterSession:
    raw = json.loads(cookie_json) if isinstance(cookie_json, str) else cookie_json
    cookies = [SellerCenterCookie.from_dict(c) for c in raw]
    return SellerCenterSession(cookies=cookies, shop_id=shop_id)


class SellerCenterClient:
    def __init__(self, session: SellerCenterSession | None = None, cookies_path: str = COOKIES_FILE):
        self.cookies_path = cookies_path
        if session is None:
            session = load_cookies(cookies_path)
        self.session = session
        self._requests_session: requests.Session | None = None
        self._last_request_time = 0.0
        self._min_interval = 0.5

    def is_authenticated(self) -> bool:
        return self.session is not None and self.session.is_valid()

    def _ensure_session(self) -> requests.Session:
        if self._requests_session is None:
            if not self.is_authenticated():
                raise RuntimeError(
                    "Seller Center nao autenticado. "
                    "Use `laura seller-center-import` para importar cookies do navegador."
                )
            self._requests_session = self.session.get_requests_session()
        return self._requests_session

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        s = self._ensure_session()
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
        kwargs.setdefault("timeout", 30)
        resp = s.request(method, url, **kwargs)
        if resp.status_code == 401 or resp.status_code == 403:
            warning(f"Seller Center auth failed ({resp.status_code}) - cookies may be expired")
        return resp

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        csrf = self.session.get_cookie("SPC_ST") if self.session else None
        if csrf:
            kwargs.setdefault("headers", {})
            kwargs["headers"].setdefault("X-CSRFToken", csrf.value)
            kwargs["headers"].setdefault("X-Requested-With", "XMLHttpRequest")
        return self._request("POST", url, **kwargs)

    # === Business methods (Seller Center Web API) ===

    def get_shop_info(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/selleraccount/shop_info/")
        return resp.json().get("data", {}) if resp.ok else {}

    def get_user_info(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/selleraccount/user_info/")
        return resp.json().get("data", {}) if resp.ok else {}

    def get_login_info(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v2/login/")
        return resp.json() if resp.ok else {}

    def get_todo_summary(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/miscellaneous/homepage/get_to_do_list_summary/")
        return resp.json().get("data", {}) if resp.ok else {}

    def get_shop_settings(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/sellermisc/sc_conf/get_shop_settings/")
        return resp.json().get("data", {}) if resp.ok else {}

    def get_shop_inactive_status(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/sellermisc/shop_info/get_shop_inactive_status/")
        return resp.json().get("data", {}) if resp.ok else {}

    def get_feature_toggles(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/sellermisc/feature_toggle/get_shop_feature_toggles/")
        return resp.json() if resp.ok else {}

    # === Legacy (may 404, kept for backward compat) ===

    def get_shop_overview(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/shop/overview")
        return resp.json() if resp.ok else {}

    def get_financial_summary(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/finance/overview")
        return resp.json() if resp.ok else {}

    def get_violation_records(self) -> list[dict[str, Any]]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/penalty/records")
        return resp.json().get("data", []) if resp.ok else []

    def get_shop_health(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/shop/health")
        return resp.json() if resp.ok else {}

    def get_marketing_campaigns(self) -> list[dict[str, Any]]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/marketing/campaigns")
        return resp.json().get("data", []) if resp.ok else []

    def get_chat_conversations(self) -> list[dict[str, Any]]:
        resp = self.get(f"{SHOPEE_BASE}/api/v2/chat/conversations")
        return resp.json().get("data", []) if resp.ok else []

    def get_shop_performance_details(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/shop/performance")
        return resp.json() if resp.ok else {}

    def get_payout_history(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        resp = self.get(
            f"{SELLER_CENTER_BASE}/api/v1/finance/payouts",
            params={"page": page, "limit": limit},
        )
        return resp.json().get("data", []) if resp.ok else []

    def get_product_listing_issues(self) -> list[dict[str, Any]]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/product/listing-issues")
        return resp.json().get("data", []) if resp.ok else []

    def get_rating_breakdown(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v1/shop/ratings")
        return resp.json() if resp.ok else []

    # === Pedidos (legacy) ===

    def get_orders(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/order/get_order_list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    def get_returns(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/order/return_refund",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    # === Produtos (legacy) ===

    def get_products(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/product/get_item_list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    def get_standard_products(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/product/get_stand_product_list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    # === Saude da Loja (legacy) ===

    def get_account_health(self) -> dict[str, Any]:
        try:
            resp = self.get(f"{SELLER_CENTER_BASE}/portal/api/v2/account_health/get_data")
            return resp.json() if resp.ok else {}
        except Exception:
            return {}

    def get_appeals(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/appeal/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    # === Financeiro (legacy) ===

    def get_income(self, page: int = 1, limit: int = 20) -> dict[str, Any]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/finance/income/get_data",
                params={"page": page, "limit": limit},
            )
            return resp.json() if resp.ok else {}
        except Exception:
            return {}

    def get_wallet_balance(self) -> dict[str, Any]:
        try:
            resp = self.get(f"{SELLER_CENTER_BASE}/portal/api/v2/finance/wallet/get_balance")
            return resp.json() if resp.ok else {}
        except Exception:
            return {}

    # === Marketing (legacy) ===

    def get_campaigns(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/marketing/campaign/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    def get_vouchers(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/marketing/voucher/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    def get_flash_sales(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/marketing/flash_sale/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    # === Chat / Atendimento (legacy) ===

    def get_chat_management(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/chat/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    def get_crm_broadcasts(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/crm/broadcast/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    # === Avaliacoes ===

    def get_ratings(self, page: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        try:
            resp = self.get(
                f"{SELLER_CENTER_BASE}/portal/api/v2/rating/list",
                params={"page": page, "limit": limit},
            )
            return resp.json().get("data", []) if resp.ok else []
        except Exception:
            return []

    # === Avaliacoes (v3 - funciona) ===

    def get_rating_dashboard(self) -> dict[str, Any]:
        resp = self.get(f"{SELLER_CENTER_BASE}/api/v3/settings/get_rating_dashboard/")
        return resp.json().get("data", {}) if resp.ok else {}

    def get_rating_comments(self, rating_star: str = "5,4,3,2,1", page: int = 1, page_size: int = 20, cursor: int = 0) -> list[dict[str, Any]]:
        resp = self.get(
            f"{SELLER_CENTER_BASE}/api/v3/settings/search_shop_rating_comments_new/",
            params={"rating_star": rating_star, "page_number": page, "page_size": page_size, "cursor": cursor, "from_page_number": page},
        )
        return resp.json().get("data", {}).get("list", []) if resp.ok else []

    def reply_to_rating(self, order_id: int, comment_id: int, comment: str) -> bool:
        resp = self.post(
            f"{SELLER_CENTER_BASE}/api/v3/settings/reply_shop_rating/",
            json={"order_id": order_id, "comment_id": comment_id, "comment": comment},
        )
        if resp.ok:
            data = resp.json()
            return data.get("code") == 0
        return False

    # === Config ===

    def get_shipping_settings(self) -> dict[str, Any]:
        try:
            resp = self.get(f"{SELLER_CENTER_BASE}/portal/api/v2/setting/shipping/get")
            return resp.json() if resp.ok else {}
        except Exception:
            return {}

    def get_shop_profile(self) -> dict[str, Any]:
        try:
            resp = self.get(f"{SELLER_CENTER_BASE}/portal/api/v2/setting/shop_profile/get")
            return resp.json() if resp.ok else {}
        except Exception:
            return {}

    def get_pickup_settings(self) -> dict[str, Any]:
        """Tenta obter configuracao de retirada pelo comprador."""
        candidates = [
            "/portal/api/v2/setting/shipping/pickup/get",
            "/portal/api/v2/setting/pickup/get",
            "/api/v2/setting/shipping/pickup",
            "/portal/api/v2/shipping/pickup_setting",
            "/portal/api/v2/shipping/preferred-pickup-time/get",
            "/portal/api/v2/logistics/direct-delivery-setting/get",
        ]
        for path in candidates:
            try:
                resp = self.get(f"{SELLER_CENTER_BASE}{path}")
                if resp.ok and resp.json().get("code") == 0:
                    return resp.json()
            except Exception:
                continue
        return {"error": "Endpoint de retirada nao encontrado. Use o navegador manualmente para descobrir."}

    def enable_pickup(self, enable: bool = True) -> dict:
        """Tenta ativar/desativar retirada pelo comprador."""
        candidates = [
            ("/portal/api/v2/setting/shipping/pickup/update", {"enabled": enable}),
            ("/portal/api/v2/setting/pickup/update", {"enabled": enable}),
            ("/api/v2/setting/shipping/pickup", {"enabled": enable}),
            ("/portal/api/v2/shipping/pickup_setting", {"enabled": enable}),
            ("/portal/api/v2/shipping/preferred-pickup-time/update", {"enabled": enable}),
        ]
        for path, data in candidates:
            try:
                resp = self.post(f"{SELLER_CENTER_BASE}{path}", json=data)
                if resp.ok and resp.json().get("code") == 0:
                    return {"success": True, "endpoint": path, "data": data}
            except Exception:
                continue
        return {"error": "Nenhum endpoint de retirada funcionou. Use o navegador manualmente para descobrir."}

    def summarize(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "authenticated": self.is_authenticated(),
        }
        if not self.is_authenticated():
            return result

        try:
            overview = self.get_shop_overview()
            result["overview"] = overview
        except Exception as e:
            result["overview_error"] = str(e)

        try:
            health = self.get_shop_health()
            result["health"] = health
        except Exception as e:
            result["health_error"] = str(e)

        try:
            financial = self.get_financial_summary()
            result["financial"] = financial
        except Exception as e:
            result["financial_error"] = str(e)

        try:
            violations = self.get_violation_records()
            result["violations_count"] = len(violations)
        except Exception as e:
            result["violations_error"] = str(e)

        try:
            orders = self.get_orders(limit=5)
            result["recent_orders_count"] = len(orders)
            result["recent_orders"] = orders
        except Exception as e:
            result["orders_error"] = str(e)

        try:
            products = self.get_products(limit=5)
            result["products_count"] = len(products)
            result["recent_products"] = products
        except Exception as e:
            result["products_error"] = str(e)

        try:
            account_health = self.get_account_health()
            result["account_health"] = account_health
        except Exception as e:
            result["account_health_error"] = str(e)

        try:
            wallet = self.get_wallet_balance()
            result["wallet_balance"] = wallet
        except Exception as e:
            result["wallet_error"] = str(e)

        try:
            campaigns = self.get_campaigns(limit=5)
            result["campaigns_count"] = len(campaigns)
        except Exception as e:
            result["campaigns_error"] = str(e)

        try:
            ratings = self.get_ratings(limit=5)
            result["ratings_count"] = len(ratings)
            result["recent_ratings"] = ratings
        except Exception as e:
            result["ratings_error"] = str(e)

        return result

    def enrich_context(self) -> dict[str, Any]:
        if not self.is_authenticated():
            return {"seller_center": "nao autenticado"}
        ctx: dict[str, Any] = {}
        try:
            health = self.get_shop_health()
            ctx["shop_health_score"] = health.get("health_score", "N/A")
        except Exception:
            pass
        try:
            violations = self.get_violation_records()
            ctx["active_violations"] = len(violations)
        except Exception:
            pass
        try:
            financial = self.get_financial_summary()
            ctx["available_balance"] = financial.get("available_balance", "N/A")
            ctx["pending_payout"] = financial.get("pending_payout", "N/A")
        except Exception:
            pass
        return ctx


def cli_import(cookie_json: str, shop_id: str | None = None) -> bool:
    session = import_from_browser(cookie_json, shop_id=shop_id)
    return save_cookies(session)


def cli_status(cookies_path: str = COOKIES_FILE) -> dict[str, Any]:
    session = load_cookies(cookies_path)
    if session is None:
        return {"authenticated": False, "error": "Nenhum cookie encontrado"}
    client = SellerCenterClient(session)
    result = client.summarize()
    result["cookies_count"] = len(session.cookies)
    result["valid"] = session.is_valid()
    return result
