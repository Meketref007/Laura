"""Find real API endpoints from Seller Center JS bundles."""
import json, re, sys
from pathlib import Path

import requests

SELLER = "https://seller.shopee.com.br"

cookies_file = Path("secrets/seller_center_cookies.json")
data = json.loads(cookies_file.read_text())

session = requests.Session()
for c in data.get("cookies", []):
    session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"), secure=c.get("secure", True))

session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
})

# Get app-config JS
config_url = "https://deo.shopeemobile.com/shopee/shopee-seller-live-br/mmf_portal_seller_root_dir/static/portal/local-seller-center/app-config.d8939add6497bf10c28951681fbdf05f.js"
resp = session.get(config_url, timeout=15)
js_text = resp.text
print(f"=== Config JS ({len(js_text)} chars) ===")

# Extract all URLs and API paths
urls = re.findall(r'["\'](https?://[^"\']+)["\']', js_text)
print(f"\nFound {len(urls)} URLs in config")
for u in urls[:30]:
    print(f"  {u}")

# Check for common keys
for key in ["api", "baseUrl", "base_url", "endpoint", "gateway", "graphql", "host"]:
    matches = re.findall(rf'["\']{key}["\']\s*:\s*["\']([^"\']+)["\']', js_text, re.IGNORECASE)
    if matches:
        print(f"\n{key}: {matches[:5]}")

# Try to find API gateway pattern
gateways = re.findall(r'["\'](https?://[^"\']*(?:gateway|api-gw|api-gateway)[^"\']*)["\']', js_text)
print(f"\nGateways: {gateways}")

# Try common Shopee internal API hosts
test_hosts = [
    "https://sf.shopee.com.br",
    "https://banana.shopee.com.br",
    "https://pm.shopee.com.br",
    "https://mall.shopee.com.br",
    "https://shopee.com.br/api/v4",
    "https://seller.shopee.com.br/api/v2",
    "https://seller.shopee.com.br/api/v3",
    "https://seller.shopee.com.br/api/v4",
]
print("\n=== Testing common hosts ===")
for host in test_hosts:
    try:
        resp = session.get(f"{host}/shop/overview" if "api" in host else f"{host}/api/v1/shop/overview", timeout=10)
        print(f"[{resp.status_code}] {host}")
        if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
            print(f"  JSON: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERR] {host}: {e}")
