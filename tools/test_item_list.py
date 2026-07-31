"""Check item list via Open API and try update with logistic_info."""
import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import dotenv
dotenv.load_dotenv(".env")

from shopee_agent.config import load_config
from shopee_agent.client import ShopeeClient

cfg = load_config()
client = ShopeeClient(cfg)
token = cfg.default_access_token
shop_id = cfg.default_shop_id

print(f"Shop ID: {shop_id}")

# 1. Get item list to check if our products are accessible
resp = client.get_item_list(access_token=token, shop_id=shop_id, offset=0, page_size=10)
if resp.status_code == 200:
    items = resp.data.get("response", {}).get("item", []) or resp.data.get("item_list", [])
    print(f"Items found: {len(items)}")
    for item in items[:5]:
        print(f"  ID: {item.get('item_id')} | Name: {item.get('item_name', '')[:40]}")
else:
    print(f"List error: {resp.status_code} {json.dumps(resp.data, indent=2)[:500]}")

# 2. Try get_item_detail with a different item
item_ids = [20798021441, 23793682648, 58256032299]
for iid in item_ids:
    resp = client.get_item_detail(access_token=token, shop_id=shop_id, item_id=iid)
    if resp.status_code == 200:
        item = resp.data.get("response", {}).get("item", {})
        logistic = item.get("logistic_info", "N/A")
        print(f"\nItem {iid}: logistic_info present = {logistic != 'N/A'}")
        if logistic != "N/A":
            print(f"  logistic_info: {json.dumps(logistic, indent=2, ensure_ascii=False)[:500]}")
    else:
        print(f"\nItem {iid}: error {resp.status_code} - {json.dumps(resp.data, indent=2)[:200]}")
