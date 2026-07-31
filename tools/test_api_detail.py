"""Check item detail API for logistics info."""
import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

os.environ["SELLER_CENTER_DRY_RUN"] = "0"
from shopee_agent.client import ShopeeClient
from shopee_agent.auth import get_access_token
from shopee_agent.seller_center import load_cookies

if not load_cookies():
    print("Cookies not valid")
    sys.exit(1)

token = get_access_token()
if not token:
    print("No access token")
    sys.exit(1)

client = ShopeeClient()
resp = client.get_item_detail(access_token=token, shop_id=os.getenv("SHOPEE_SHOP_ID", 0), item_id=58256032299)
if resp:
    data = resp.data if hasattr(resp, "data") else resp
    if isinstance(data, dict):
        item = data.get("item", data)
        logistic = item.get("logistic_info", item.get("logistics", "NOT FOUND"))
        print(f"logistic_info: {json.dumps(logistic, indent=2, ensure_ascii=False)[:2000]}")
        print(f"\nItem keys: {list(item.keys())[:20]}")
    else:
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)[:1000]}")
else:
    print(f"No response or error")
