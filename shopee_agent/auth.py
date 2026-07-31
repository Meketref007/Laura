from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from .config import ShopeeConfig


def unix_timestamp() -> int:
    return int(time.time())


def sign_request(
    *,
    partner_id: int,
    partner_key: str,
    path: str,
    timestamp: int,
    access_token: str | None = None,
    shop_id: int | None = None,
) -> str:
    token_part = access_token or ""
    shop_part = str(shop_id) if shop_id is not None else ""
    base_string = f"{partner_id}{path}{timestamp}{token_part}{shop_part}"
    return hmac.new(
        partner_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_shop_authorization_url(config: ShopeeConfig, timestamp: int | None = None) -> str:
    path = "/api/v2/shop/auth_partner"
    ts = timestamp if timestamp is not None else unix_timestamp()
    sign = sign_request(
        partner_id=config.partner_id,
        partner_key=config.partner_key,
        path=path,
        timestamp=ts,
    )

    params = {
        "partner_id": config.partner_id,
        "timestamp": ts,
        "redirect": config.redirect_url,
        "sign": sign,
    }

    return f"{config.base_url}{path}?{urlencode(params)}"
