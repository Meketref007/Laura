"""Busca endpoints de shipping/pickup nos JS bundles do Seller Center."""
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

found = []
for src in scripts:
    if not src.startswith("http"):
        src = SELLER_CENTER_BASE + src
    try:
        js = client.get(src, timeout=15).text
        if "shipping" not in js.lower():
            continue
        # Procura por strings delimitadas que contem shipping + api
        for m in re.finditer(r"'([^']*(?:shipping|setting|pickup|logistics|delivery)[^']*)'", js, re.IGNORECASE):
            val = m.group(1)
            if "api" in val.lower() or "/v2/" in val or "/v1/" in val:
                found.append(val)
    except Exception as e:
        pass

print(f"\nEndpoints de shipping/setting/pickup encontrados:")
for ep in sorted(set(found)):
    print(f"  {ep}")
