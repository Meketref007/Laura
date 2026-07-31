"""Test _scrape_via_cdp directly."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shopee_agent.competitive_intelligence import CompetitiveIntelligence
ci = CompetitiveIntelligence(path='reports/competitive_offers.jsonl')
items = ci._scrape_via_cdp("Smartwatch Xiaomi Band 8", max_items=3)
print(f'Items returned: {len(items)}')
if items:
    for entry in items[:3]:
        item = entry.get("item_basic", entry)
        name = item.get("name", "?")
        price = float(item.get("price", 0)) / 100000
        print(f'  - {name[:50]} R${price:.2f}')
else:
    print("No items found (Shopee blocking)")
