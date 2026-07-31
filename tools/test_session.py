"""Debug Open API product list - check response details."""
import io, sys, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from shopee_agent.config import load_config

cfg = load_config()
access_token = cfg.default_access_token or os.getenv("SHOPEE_ACCESS_TOKEN", "")
shop_id = cfg.default_shop_id or int(os.getenv("SHOPEE_SHOP_ID", "0"))

from shopee_agent.client import ShopeeClient
client = ShopeeClient(cfg)

resp = client.get_item_list(access_token=access_token, shop_id=shop_id, page_size=10)
body = resp.data
if isinstance(body, dict):
    api_body = body.get("response", body)
    print(f"Full response keys: {list(api_body.keys())}")
    print(f"total_count: {api_body.get('total_count')}")
    print(f"has_next_page: {api_body.get('has_next_page')}")
    items = api_body.get("item", [])
    print(f"items in 'item' key: {len(items)}")
    # Also try item_list
    items2 = api_body.get("item_list", [])
    print(f"items in 'item_list' key: {len(items2)}")
    # Maybe the key is different
    for k, v in api_body.items():
        if isinstance(v, list):
            print(f"  List key: {k} (len={len(v)})")
            if v:
                print(f"    sample: {json.dumps(v[0], ensure_ascii=False)[:200]}")
        elif isinstance(v, (int, str)):
            print(f"  Scalar: {k} = {v}")
    # Check if 'item' is a dict
    item = api_body.get("item")
    if isinstance(item, dict):
        print(f"item is dict with keys: {list(item.keys())}")

print("\n=== Trying with different status ===")
# Maybe need to filter by status
for status in ["NORMAL", "LIVE", "UNLIST", "BANNED"]:
    resp = client.get_item_list(access_token=access_token, shop_id=shop_id, page_size=5, item_status=[status])
    body = resp.data
    if isinstance(body, dict):
        api_body = body.get("response", body)
        tc = api_body.get("total_count", 0)
        print(f"  status={status}: total_count={tc}")
