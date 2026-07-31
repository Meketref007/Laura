"""Discover Seller Center API endpoints by testing common patterns."""
import json, sys, time
from pathlib import Path

import requests

SELLER = "https://seller.shopee.com.br"
SHOPEE = "https://shopee.com.br"

cookies_file = Path("secrets/seller_center_cookies.json")
if not cookies_file.exists():
    print("ERROR: No cookies file found")
    sys.exit(1)

data = json.loads(cookies_file.read_text())
session = requests.Session()
for c in data.get("cookies", []):
    session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"), secure=c.get("secure", True))

session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": SELLER,
    "Referer": f"{SELLER}/",
})

csrf = None
for c in data.get("cookies", []):
    if c["name"] == "SPC_ST":
        csrf = c["value"]
        break

endpoints = [
    # Seller Center common API patterns
    ("GET", f"{SELLER}/api/v1/shop/overview"),
    ("GET", f"{SELLER}/api/v1/shop/health"),
    ("GET", f"{SELLER}/api/v1/finance/overview"),
    ("GET", f"{SELLER}/api/v1/finance/payouts"),
    ("GET", f"{SELLER}/api/v1/penalty/records"),
    ("GET", f"{SELLER}/api/v1/shop/performance"),
    ("GET", f"{SELLER}/api/v1/shop/ratings"),
    ("GET", f"{SELLER}/api/v1/marketing/campaigns"),
    ("GET", f"{SELLER}/api/v1/product/listing-issues"),
    # Alternative patterns
    ("GET", f"{SELLER}/api/v2/shop/overview"),
    ("GET", f"{SELLER}/api/v2/finance/overview"),
    ("GET", f"{SELLER}/api/v2/penalty/records"),
    ("GET", f"{SELLER}/api/v2/shop/health"),
    ("GET", f"{SELLER}/api/v2/order/list"),
    ("GET", f"{SELLER}/api/v2/product/list"),
    # Portal patterns
    ("GET", f"{SELLER}/portal/api/shop/overview"),
    ("GET", f"{SELLER}/portal/api/shop/health"),
    ("GET", f"{SELLER}/portal/api/finance/overview"),
    ("GET", f"{SELLER}/portal/api/penalty"),
    # Shopee common patterns with seller cookies
    ("GET", f"{SHOPEE}/api/v1/shop/overview"),
    ("GET", f"{SHOPEE}/api/v2/order/get_order_list?page_size=1"),
    ("GET", f"{SHOPEE}/api/v2/product/get_item_list?page_size=1&item_status=NORMAL"),
    # Try to find API via common prefixes
    ("GET", f"{SELLER}/api/account/overview"),
    ("GET", f"{SELLER}/api/account/profile"),
    ("GET", f"{SELLER}/api/shop/info"),
    # Seller account / session check
    ("GET", f"{SELLER}/api/auth/check"),
    ("GET", f"{SELLER}/api/v1/auth/check"),
    # Try graphql
    ("POST", f"{SELLER}/api/graphql"),
    ("POST", f"{SELLER}/graphql"),
]

for method, url in endpoints:
    try:
        headers = {}
        if csrf and method == "POST":
            headers["X-CSRFToken"] = csrf
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Content-Type"] = "application/json"
        resp = session.request(method, url, headers=headers, timeout=15, json={"query": "{ shop { id name } }"} if "graphql" in url else None)
        status = resp.status_code
        body = ""
        if status == 200:
            ct = resp.headers.get("content-type", "")
            if "json" in ct or "javascript" in ct:
                try:
                    data = resp.json()
                    keys = list(data.keys()) if isinstance(data, dict) else "array"
                    body = f"OK keys={keys} preview={json.dumps(data)[:200]}"
                except:
                    body = f"OK but not JSON: {resp.text[:100]}"
            else:
                body = f"OK content-type={ct} len={len(resp.content)}"
        elif status in (401, 403):
            body = f"AUTH FAIL: {resp.text[:100]}"
        elif status == 404:
            body = "404"
        else:
            body = f"{status}: {resp.text[:100]}"
        print(f"[{status}] {method} {url}")
        if status == 200:
            print(f"  -> {body}")
    except Exception as e:
        print(f"[ERR] {method} {url}: {e}")
