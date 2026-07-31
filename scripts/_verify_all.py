import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shopee_agent.config import load_config
from shopee_agent.client import ShopeeClient

cfg = load_config()
c = ShopeeClient(cfg)
token = cfg.default_access_token
shop_id = cfg.default_shop_id

items = []
offset = 0
while True:
    r = c.get_item_list(
        access_token=token, shop_id=shop_id, offset=offset, page_size=100
    )
    resp = r.data.get("response", {})
    items.extend(resp.get("item", []) or [])
    if resp.get("has_next_page"):
        offset = resp.get("next_offset")
    else:
        break

ids = [it["item_id"] for it in items]
print(f"Total de itens: {len(ids)}")

ok = 0
fails = []
for i in range(0, len(ids), 20):
    chunk = ids[i : i + 20]
    r = c._request(
        "/api/v2/product/get_item_base_info",
        "GET",
        access_token=token,
        shop_id=shop_id,
        query_params={"item_id_list": chunk},
    )
    for it in r.data.get("response", {}).get("item_list", []) or []:
        po = it.get("pre_order") or {}
        if po.get("is_pre_order") and po.get("days_to_ship") == 3:
            ok += 1
        else:
            fails.append((it["item_id"], po, it.get("category_id")))
    time.sleep(1)

print(f">>> {ok}/{len(ids)} com pre-order ativo")
for f in fails:
    print(f"  FALHOU: {f}")
