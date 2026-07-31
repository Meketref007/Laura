"""Busca endpoints na config JS que tem as rotas de shipping/pickup."""
import sys, re
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from shopee_agent.seller_center import SellerCenterClient

client = SellerCenterClient()

url = "https://deo.shopeemobile.com/shopee/shopee-seller-live-br/mmf_portal_seller_root_dir/static/portal/local-seller-center/app-config.ac4ac6ca3cb83a07c33a122ad9e666dd.js"
js = client.get(url).text

# Procura por strings contendo api + shipping/setting/pickup/logistics
pattern = re.compile(r"'([^']*(?:api|v2|v1)[^']*(?:shipping|setting|pickup|logistics|delivery)[^']*)'", re.IGNORECASE)
for m in pattern.finditer(js):
    print(m.group(1))

# Procura por contexto JSON ao redor de 'pickup'
idx = js.lower().find("pickup")
while idx != -1:
    start = max(0, idx - 100)
    end = min(len(js), idx + 200)
    ctx = js[start:end]
    # Extrai linhas
    for line in ctx.split("\n"):
        line = line.strip()
        if line and len(line) > 10:
            print(f"\nCONTEXT: {line[:200]}")
    idx = js.lower().find("pickup", idx + 1)
