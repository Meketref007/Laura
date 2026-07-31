"""Shared helpers for cli_commands modules.
All functions are copied from cli.py to avoid circular imports.
"""
from __future__ import annotations

import json
import os
import sys


def print_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))

def ensure_no_api_error(data, context="API call"):
    if isinstance(data, dict):
        err = data.get("error")
        if err:
            msg = data.get("message", "") or data.get("msg", "")
            print(f"API error: {err} - {msg}", file=sys.stderr)
            return None
        if data.get("response"):
            if data["response"].get("error"):
                err = data["response"]["error"]
                msg = data["response"].get("message", "")
                print(f"API error: {err} - {msg}", file=sys.stderr)
                return None
    return data

def refresh_default_access_token(cfg):
    """Force refresh of the default access token using the stored refresh token."""
    from shopee_agent.shopee_api import ShopeeClient
    shop_id = int(cfg.get("SHOPEE_DEFAULT_SHOP_ID", 0))
    refresh_token = cfg.get("SHOPEE_DEFAULT_REFRESH_TOKEN", "")
    if not refresh_token:
        print("No default refresh token found in config.", file=sys.stderr)
        return None
    client = ShopeeClient(cfg)
    data = client._call_refresh_token(
        shop_id=shop_id,
        refresh_token=refresh_token,
        partner_id=int(cfg.get("SHOPEE_PARTNER_ID", "0")),
        partner_key=cfg.get("SHOPEE_PARTNER_KEY", ""),
    )
    data = ensure_no_api_error(data, "token refresh")
    if data and "access_token" in data.get("response", {}):
        new_token = data["response"]["access_token"]
        upsert_env_values({"SHOPEE_DEFAULT_ACCESS_TOKEN": new_token})
        print("Token refreshed and saved to .env")
        return new_token
    print("Failed to refresh token.", file=sys.stderr)
    return None

def upsert_env_values(updates, env_path=".env"):
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            for k, v in updates.items():
                f.write(f"{k}={v}\n")
        return
    with open(env_path) as f:
        lines = f.readlines()
    for k, v in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{k}="):
                lines[i] = f"{k}={v}\n"
                found = True
                break
        if not found:
            lines.append(f"{k}={v}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

def append_audit_line(filepath, entry):
    """Append a JSON line to an audit file."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

def load_json_file(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def coerce_positive_float(val, default=1.0):
    if val is None:
        return default
    try:
        v = float(val)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default

def coerce_positive_int(val, default=1):
    if val is None:
        return default
    try:
        v = int(val)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default

def first_present_text(*args):
    for a in args:
        if a is not None and str(a).strip():
            return str(a).strip()
    return None

def normalize_lookup_text(text):
    if not text:
        return ""
    return "".join(text.lower().split())

def int_from_env(key, default):
    raw = os.environ.get(key, str(default)).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
