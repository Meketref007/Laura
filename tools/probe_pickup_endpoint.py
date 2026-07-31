"""Provar automaticamente endpoints de retirada no Seller Center."""
import json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from shopee_agent.seller_center import SellerCenterClient

client = SellerCenterClient()
if not client.is_authenticated():
    print("Seller Center nao autenticado")
    sys.exit(1)

# Tenta diversos endpoints de GET para descobrir pickup settings
get_candidates = [
    "/portal/api/v2/setting/shipping/pickup/get",
    "/api/v2/setting/shipping/pickup/get",
    "/portal/api/v2/setting/pickup/get",
    "/api/v2/setting/pickup/get",
    "/api/v2/shipping/pickup/get",
    "/api/v2/shipping/pickup_setting",
    "/api/v2/setting/shipping/pickup_setting",
    "/api/v2/setting/shipping/pickup_setting/get",
    "/api/v2/setting/get_pickup_setting",
    "/api/v2/shipping/get_pickup_setting",
]

WORKED = None
for path in get_candidates:
    url = f"https://seller.shopee.com.br{path}"
    try:
        resp = client.get(url)
        body = resp.json()
        code = body.get("code", -1)
        msg = body.get("message", "")
        if code == 0:
            print(f"OK: {path} -> code={code}")
            print(f"   data: {json.dumps(body, ensure_ascii=False)[:300]}")
            if WORKED is None:
                WORKED = path
        elif code == 100001:
            pass  # not found
        else:
            print(f"   path={path} status={resp.status_code} code={code} msg={msg[:80]}")
    except Exception as e:
        pass

if not WORKED:
    print("Nenhum endpoint GET funcionou. Tentando pagina de configuracao...")
    # Tenta paginas HTML
    html_paths = [
        "/portal/setting/shipping",
        "/portal/seller/shipping",
        "/portal/webview/shipping",
    ]
    for path in html_paths:
        url = f"https://seller.shopee.com.br{path}"
        try:
            resp = client.get(url)
            text = resp.text.lower()
            if "retirada" in text or "pickup" in text:
                print(f"Pagina {path} contem 'retirada': status={resp.status_code}")
                # Extrai URLs de API da pagina
                import re
                apis = re.findall(r'/api/v2/[^"\'\\s]+', text)
                for a in apis:
                    if "pickup" in a or "retirada" in a:
                        print(f"  Possivel endpoint: {a}")
                break
        except:
            pass
