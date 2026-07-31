"""Test toggle shipping channel live."""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

os.environ["SELLER_CENTER_DRY_RUN"] = "0"

from shopee_agent.seller_center_actions import execute_action

result = execute_action("set_product_shipping_channel", item_id=58256032299, channel="Retirada pelo Comprador", enable=True)
print(result)
