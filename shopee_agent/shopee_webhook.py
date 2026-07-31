from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from shopee_agent.client import ShopeeClient
from shopee_agent.config import load_config

PUBLIC_BASE_URL = os.getenv("LAURA_WEBHOOK_PUBLIC_BASE_URL", "https://webhook.agentelaura.uk")
WEBHOOK_PATH = os.getenv("LAURA_WEBHOOK_PATH", "/webhook/shopee")

DEFAULT_EVENT_TYPES = [
    "ORDER_CREATED",
    "ORDER_STATUS_CHANGED",
    "RETURN_REFUND_CREATED",
    "SHIPMENT_ORDER_PICKUP",
    "ITEM_STOCK_CHANGE",
    "ITEM_PROMOTION_CREATED",
]


def _get_client() -> ShopeeClient:
    config = load_config()
    return ShopeeClient(config)


def register_webhook(
    *,
    shop_id: int | None = None,
    access_token: str | None = None,
    webhook_url: str | None = None,
    interest_list: list[str] | None = None,
) -> dict[str, Any]:
    """Register a webhook via Shopee Push API (/api/v2/push/set_push_config)."""
    config = load_config()
    sid = shop_id if shop_id is not None else config.default_shop_id
    token = access_token if access_token is not None else config.default_access_token

    if sid is None:
        raise ValueError("shop_id is required")
    if token is None:
        raise ValueError("access_token is required")

    url = webhook_url or f"{PUBLIC_BASE_URL}{WEBHOOK_PATH}"
    interests = interest_list if interest_list is not None else DEFAULT_EVENT_TYPES

    client = _get_client()
    resp = client.set_push_config(
        access_token=token,
        shop_id=sid,
        callback_url=url,
        interest_list=interests,
    )
    if hasattr(resp, "data"):
        return resp.data if isinstance(resp.data, dict) else {"response": str(resp.data)}
    return {"response": str(resp)}


def list_webhooks(
    *,
    shop_id: int | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """List registered webhooks via Shopee Push API (/api/v2/push/get_push_config)."""
    config = load_config()
    sid = shop_id if shop_id is not None else config.default_shop_id
    token = access_token if access_token is not None else config.default_access_token

    if sid is None:
        raise ValueError("shop_id is required")
    if token is None:
        raise ValueError("access_token is required")

    client = _get_client()
    resp = client.get_push_config(
        access_token=token,
        shop_id=sid,
    )
    if hasattr(resp, "data"):
        return resp.data if isinstance(resp.data, dict) else {"response": str(resp.data)}
    return {"response": str(resp)}


def delete_webhook(
    webhook_id: str,
    *,
    shop_id: int | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Delete a webhook by setting empty callback URL via Push API."""
    config = load_config()
    sid = shop_id if shop_id is not None else config.default_shop_id
    token = access_token if access_token is not None else config.default_access_token

    if sid is None:
        raise ValueError("shop_id is required")
    if token is None:
        raise ValueError("access_token is required")

    client = _get_client()
    resp = client.set_push_config(
        access_token=token,
        shop_id=sid,
        callback_url="",
        event_type_list=[],
    )
    if hasattr(resp, "data"):
        return resp.data if isinstance(resp.data, dict) else {"response": str(resp.data)}
    return {"response": str(resp)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Shopee Webhook Manager (Push API)")
    sub = parser.add_subparsers(dest="command", required=True)

    register_parser = sub.add_parser("register", help="Register webhook")
    register_parser.add_argument("--webhook-url", help="Callback URL (default: LAURA_WEBHOOK_PUBLIC_BASE_URL + WEBHOOK_PATH)")
    register_parser.add_argument("--shop-id", type=int, help="Shopee shop ID (default: config)")
    register_parser.add_argument("--access-token", help="Access token (default: config)")
    register_parser.add_argument("--interest-list", nargs="*", default=None, help="Event types to subscribe (default: all)")
    sub.add_parser("list", help="List registered webhooks")

    del_parser = sub.add_parser("delete", help="Delete a webhook")
    del_parser.add_argument("webhook_id", help="ID of the webhook to delete")

    args = parser.parse_args()

    try:
        if args.command == "register":
            kwargs = {}
            if getattr(args, "webhook_url", None):
                kwargs["webhook_url"] = args.webhook_url
            if getattr(args, "shop_id", None):
                kwargs["shop_id"] = args.shop_id
            if getattr(args, "access_token", None):
                kwargs["access_token"] = args.access_token
            if getattr(args, "interest_list", None):
                kwargs["interest_list"] = args.interest_list
            result = register_webhook(**kwargs)
        elif args.command == "list":
            result = list_webhooks()
        elif args.command == "delete":
            result = delete_webhook(args.webhook_id)
        else:
            parser.print_help()
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
