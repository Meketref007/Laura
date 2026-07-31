"""Auth & Shop commands: auth-url, token-get, token-refresh, token-refresh-save, shop-info, shop-info-default, auto-login."""
from __future__ import annotations

import os

from shopee_agent.auth import build_shop_authorization_url

from ._utils import ensure_no_api_error, print_json, upsert_env_values


def register_subparsers(sub):
    # auth-url
    sub.add_parser("auth-url", help="Gera URL para autorizar a loja")
    # token-get
    p = sub.add_parser("token-get", help="Troca code por access/refresh token")
    p.add_argument("--code", required=True, help="Code retornado no redirect")
    p.add_argument("--shop-id", type=int, required=True, help="ID da loja")
    # token-refresh
    p = sub.add_parser("token-refresh", help="Renova access token")
    p.add_argument("--refresh-token", required=True, help="Refresh token atual")
    p.add_argument("--shop-id", type=int, required=True, help="ID da loja")
    # token-refresh-save
    p = sub.add_parser("token-refresh-save", help="Renova token com valores padrao e salva no .env")
    p.add_argument("--env-file", default=".env", help="Caminho do arquivo .env para atualizar tokens")
    # shop-info
    p = sub.add_parser("shop-info", help="Busca informacoes da loja")
    p.add_argument("--access-token", required=True, help="Access token valido")
    p.add_argument("--shop-id", type=int, required=True, help="ID da loja")
    # shop-info-default
    sub.add_parser("shop-info-default", help="Busca informacoes da loja usando SHOPEE_DEFAULT_* do .env")
    # auto-login
    sub.add_parser("auto-login", help="Executa o loop de auto-login do Seller Center (Gmail OTP + cookies)")


def run(args, client=None, cfg=None):
    if args.command == "auth-url":
        print(build_shop_authorization_url(cfg))
        return 0

    if args.command == "token-get":
        resp = client.exchange_code_for_token(code=args.code, shop_id=args.shop_id)
        ensure_no_api_error(resp.data, "token-get")
        print_json(resp.data)
        return 0

    if args.command == "token-refresh":
        resp = client.refresh_token(refresh_token=args.refresh_token, shop_id=args.shop_id)
        ensure_no_api_error(resp.data, "token-refresh")
        print_json(resp.data)
        return 0

    if args.command == "token-refresh-save":
        if not cfg.default_refresh_token:
            print("Missing SHOPEE_DEFAULT_REFRESH_TOKEN in environment")
            return 1
        if cfg.default_shop_id is None:
            print("Missing SHOPEE_DEFAULT_SHOP_ID in environment")
            return 1
        resp = client.refresh_token(refresh_token=cfg.default_refresh_token, shop_id=cfg.default_shop_id)
        ensure_no_api_error(resp.data, "token-refresh-save")
        print_json(resp.data)
        new_access_token = str(resp.data.get("access_token", "")).strip()
        new_refresh_token = str(resp.data.get("refresh_token", "")).strip()
        if new_access_token and new_refresh_token:
            upsert_env_values(
                {"SHOPEE_DEFAULT_ACCESS_TOKEN": new_access_token, "SHOPEE_DEFAULT_REFRESH_TOKEN": new_refresh_token},
                args.env_file,
            )
        return 0

    if args.command == "shop-info":
        resp = client.get_shop_info(access_token=args.access_token, shop_id=args.shop_id)
        ensure_no_api_error(resp.data, "shop-info")
        print_json(resp.data)
        return 0

    if args.command == "shop-info-default":
        if not cfg.default_access_token:
            print("Missing SHOPEE_DEFAULT_ACCESS_TOKEN in environment")
            return 1
        if cfg.default_shop_id is None:
            print("Missing SHOPEE_DEFAULT_SHOP_ID in environment")
            return 1
        resp = client.get_shop_info(access_token=cfg.default_access_token, shop_id=cfg.default_shop_id)
        ensure_no_api_error(resp.data, "shop-info-default")
        print_json(resp.data)
        return 0

    if args.command == "auto-login":
        from shopee_agent.auto_login import auto_login_loop
        credentials_file = os.getenv("GMAIL_CREDENTIALS_FILE", "secrets/gmail_credentials.json")
        token_file = os.getenv("GMAIL_TOKEN_FILE", "secrets/gmail_token.json")
        auto_login_loop(credentials_file=credentials_file, token_file=token_file, interval_hours=6)
        return 0

    return 2
