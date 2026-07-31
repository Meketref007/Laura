"""Try Open API update_item with logistic_info."""
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

print(f"Token: {token[:20]}...")
print(f"Shop ID: {shop_id}")

# First, get current item detail
resp = client.get_item_detail(access_token=token, shop_id=shop_id, item_id=58256032299)
if resp.error:
    print(f"Error getting detail: {resp.error}")
elif resp.data:
    item = resp.data.get("item", resp.data)
    print(f"Item keys: {list(item.keys())[:30]}")
    logistic = item.get("logistic_info", "NOT FOUND")
    print(f"logistic_info: {json.dumps(logistic, indent=2, ensure_ascii=False)[:2000]}")
    
    # Try update_item with logistic_info
    print("\n--- Trying update_item with logistic_info ---")
    # Get the current logistic info to modify
    if isinstance(logistic, list):
        # Toggle first channel
        logistic_payload = list(logistic)
        if logistic_payload and len(logistic_payload) > 0:
            logistic_payload[0]["enabled"] = not logistic_payload[0].get("enabled", True)
            print(f"Modified logistic: {json.dumps(logistic_payload, indent=2, ensure_ascii=False)[:500]}")
            
            # Manual request - add logistic_info to update_item payload
            payload = {
                "item_id": 58256032299,
                "logistic_info": logistic_payload
            }
            # Use the internal _request method directly
            from shopee_agent.client import ShopeeResponse
            update_resp = client._request(
                "/api/v2/product/update_item",
                "POST",
                payload=payload,
                access_token=token,
                shop_id=shop_id,
            )
            if hasattr(update_resp, 'error') and update_resp.error:
                print(f"Update error: {update_resp.error}")
            elif hasattr(update_resp, 'data'):
                print(f"Update response: {json.dumps(update_resp.data, indent=2, ensure_ascii=False)[:500]}")
            else:
                print(f"Update response raw: {str(update_resp)[:500]}")
else:
    print(f"Response error: {resp.error if hasattr(resp, 'error') else 'unknown'}")
