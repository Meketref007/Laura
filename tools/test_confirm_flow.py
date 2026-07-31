"""Teste do fluxo de confirmacao para set_channel_for_all_products."""
import io, os, sys
from pathlib import Path
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SELLER_CENTER_DRY_RUN"] = "1"

from shopee_agent.telegram_bot import LauraTelegramBot

b = LauraTelegramBot.__new__(LauraTelegramBot)
b._seller_client = MagicMock()
b.seller_actions = MagicMock()
b.reports_dir = Path("reports")
b.access_token = "test_token"
b.shop_id = 123
b._confirmations = {}
b.client = MagicMock()
b.client.get_products.return_value = []

# Step 1: keyword matching
kw = b._match_keywords("ativar retirada pelo comprador em todos os produtos")
assert kw is not None, "keyword matching failed"
print(f"KW: intent={kw[0]}, params={kw[1]}")

# Step 2: execute intent -> confirmation
resp = b._execute_intent(kw[0], kw[1])
print(f"Response: {resp}")

cid = list(b._confirmations.keys())[0]
print(f"CID: {cid!r}")

# Step 3: handle confirm with the CID
confirm_resp = b._handle_confirm(cid)
print(f"Confirm result: {confirm_resp}")

# Step 4: direct execution
data = b._confirmations.pop(cid)
print(f"Action: {data['action']}, Params: {data['params']}")
exec_resp = b._execute_confirmed_action(data)
print(f"Exec result: {exec_resp}")

print("\nFLOW OK!")
