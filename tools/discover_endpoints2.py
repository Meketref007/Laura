"""Find real Seller Center API endpoints by inspecting the portal page."""
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

# Get the portal page HTML to find API base URLs, scripts, etc.
resp = session.get(f"{SELLER}/portal/api/shop/overview", timeout=15)
html = resp.text

# Find all script src
scripts = re.findall(r'src="([^"]+)"', html)
print("=== Scripts found ===")
for s in scripts:
    if any(x in s.lower() for x in ["api", "config", "app", "main", "vendor"]):
        print(f"  {s}")

# Find all API-like patterns
apis = re.findall(r'["\'](https?://[^"\']*api[^"\']*)["\']', html)
print(f"\n=== API URLs found ({len(apis)}) ===")
for a in apis[:20]:
    print(f"  {a}")

# Find API base URLs
bases = re.findall(r'["\'](https?://[^"\']*shopee[^"\']*/api)["\']', html)
print(f"\n=== API base URLs found ({len(bases)}) ===")
for b in bases[:10]:
    print(f"  {b}")

# Look for config objects
configs = re.findall(r'window\.\w+Config\s*=\s*({[^}]+})', html)
print(f"\n=== Config objects ({len(configs)}) ===")
for c in configs[:5]:
    print(f"  {c[:200]}")

# look for __NEXT_DATA__ or similar
next_data = re.findall(r'__NEXT_DATA__[^=]*=\s*({.+?});', html)
if next_data:
    print(f"\n=== Next data found: {next_data[0][:200]}")

print(f"\n=== HTML title ===")
titles = re.findall(r'<title>([^<]+)</title>', html)
print(f"  {titles}")

print(f"\n=== Looking for graphql or api paths ===")
all_apis = re.findall(r'["\'](/[a-zA-Z0-9_/.-]*(?:api|graphql)[a-zA-Z0-9_/.-]*)["\']', html)
for a in sorted(set(all_apis)):
    print(f"  {a}")
