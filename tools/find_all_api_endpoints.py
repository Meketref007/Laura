"""Busca TODOS os endpoints de API nos JS bundles do Seller Center."""
import sys, re, json
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from shopee_agent.seller_center import SellerCenterClient, SELLER_CENTER_BASE

client = SellerCenterClient()
resp = client.get(f"{SELLER_CENTER_BASE}/portal/setting/shipping")
html = resp.text

scripts = re.findall(r'src="([^"]+\.js[^"]*)"', html)
print(f"Found {len(scripts)} JS bundles")

all_endpoints = set()
for src in scripts:
    if not src.startswith("http"):
        src = SELLER_CENTER_BASE + src
    try:
        js = client.get(src, timeout=15).text
        # Procura por qualquer URL com /api/
        for m in re.finditer(r"['\"]([^'\"]*/api/[^'\"]*)['\"]", js):
            all_endpoints.add(m.group(1))
        # Procura por paths com /portal/api/
        for m in re.finditer(r"['\"]([^'\"]*/portal/api/[^'\"]*)['\"]", js):
            all_endpoints.add(m.group(1))
    except Exception as e:
        pass

# Filtra endpoints de shipping/setting
shipping = [ep for ep in all_endpoints if any(w in ep.lower() for w in ['shipping','setting','pickup','logistics','delivery'])]
others = [ep for ep in all_endpoints if ep not in shipping]

print(f"\nTotal endpoints encontrados: {len(all_endpoints)}")
print(f"Shipping/Setting/Pickup: {len(shipping)}")
print(f"Outros: {len(others)}")

print("\n=== SHIPPING/SETTING/PICKUP ===")
for ep in sorted(shipping):
    print(f"  {ep}")

if others:
    print(f"\n=== AMOSTRA DE OUTROS (primeiros 20) ===")
    for ep in sorted(others)[:20]:
        print(f"  {ep}")
