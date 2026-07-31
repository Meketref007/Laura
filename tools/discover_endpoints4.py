"""Find Seller Center API by checking XHR patterns and trying known Shopee internal APIs."""
import json, re, sys
from pathlib import Path

import requests

SELLER = "https://seller.shopee.com.br"
SHOPEE = "https://shopee.com.br"

cookies_file = Path("secrets/seller_center_cookies.json")
data = json.loads(cookies_file.read_text())

session = requests.Session()
for c in data.get("cookies", []):
    session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"), secure=c.get("secure", True))

csrf = None
for c in data.get("cookies", []):
    if c["name"] == "SPC_ST":
        csrf = c["value"]
        break

session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": SELLER,
    "Referer": f"{SELLER}/portal/",
})
if csrf:
    session.headers["X-CSRFToken"] = csrf
    session.headers["X-Requested-With"] = "XMLHttpRequest"

# Try common Shopee internal API patterns that the Seller Center uses
endpoints = [
    # Seller Center specific - try the portal paths with Accept: application/json
    ("GET", f"{SELLER}/portal/api/shop/overview", {"Accept": "application/json"}),
    ("GET", f"{SELLER}/portal/api/shop/health", {"Accept": "application/json"}),
    
    # Try with /api/tsp prefix (found in app-config)
    ("GET", f"{SELLER}/api/tsp/init", {}),
    
    # Shopee v4 API (used by web/app)
    ("GET", f"{SHOPEE}/api/v4/shop/get_shop_info", {}),
    ("GET", f"{SHOPEE}/api/v4/shop/get_shop_performance", {}),
    
    # Shopee v2 API (used by web)
    ("GET", f"{SHOPEE}/api/v2/shop/health", {}),
    ("GET", f"{SHOPEE}/api/v2/shop/violations", {}),
    
    # Try graphql with proper query
    ("POST", f"{SELLER}/graphql", {"Content-Type": "application/json"}),
    
    # Try the seller API with different path patterns
    ("GET", f"{SELLER}/api/seller/overview", {}),
    ("GET", f"{SELLER}/api/seller/health", {}),
    
    # Try the review prize endpoints (from JS bundle name)
    ("GET", f"{SELLER}/api/review/prize/status", {}),
    
    # Try /api/v1/account
    ("GET", f"{SELLER}/api/v1/account/info", {}),
    
    # try buyers api
    ("GET", f"{SHOPEE}/api/v4/account/basic_info", {}),
    
    # shop health - try the actual page URLs that might redirect
    ("GET", f"{SELLER}/portal/shop/health", {"Accept": "application/json"}),
    ("GET", f"{SELLER}/portal/finance/overview", {"Accept": "application/json"}),
    
    # Additional common Shopee internal endpoints
    ("GET", f"{SELLER}/api/v1/seller/penalty", {}),
    ("GET", f"{SELLER}/api/v1/seller/violation", {}),
]

for method, url, extra_headers in endpoints:
    try:
        headers = dict(session.headers)
        headers.update(extra_headers)
        resp = session.request(method, url, headers=headers, timeout=15)
        ct = resp.headers.get("content-type", "")
        status = resp.status_code
        body = ""
        if status == 200:
            if "json" in ct:
                try:
                    d = resp.json()
                    body = f"JSON keys={list(d.keys())[:10] if isinstance(d, dict) else 'array'} preview={json.dumps(d)[:300]}"
                except:
                    body = f"Invalid JSON: {resp.text[:100]}"
            elif "html" in ct:
                body = f"HTML ({len(resp.content)} bytes)"
            else:
                body = f"{ct} ({len(resp.content)} bytes)"
        elif status in (401, 403):
            body = f"AUTH: {resp.text[:100]}"
        elif status == 404:
            body = "404"
        else:
            body = f"{status}: {resp.text[:100]}"
        print(f"[{status}] {method} {url}")
        if status == 200:
            print(f"  -> {body}")
    except Exception as e:
        print(f"[ERR] {method} {url}: {e}")

# Now try to get the main vendors JS and extract API routes
print("\n=== Checking vendors JS for API routes ===")
vendors_url = "https://deo.shopeemobile.com/shopee/shopee-seller-live-sg/mmf_portal_seller_root_dir/static/portal/local-seller-center/js/vendors.97cb5cedfb5c5ee1f9bf.js"
try:
    resp = session.get(vendors_url, timeout=30)
    js = resp.text
    # Find patterns like /api/v1/resource or /api/v2/resource  
    api_paths = re.findall(r'["\'](/api/v?\d*/[a-zA-Z0-9_/-]+)["\']', js)
    unique = sorted(set(api_paths))
    print(f"Found {len(unique)} unique API paths in vendors JS:")
    for p in unique[:50]:
        print(f"  {p}")
except Exception as e:
    print(f"Error: {e}")
