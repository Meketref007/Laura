"""Test scraper with Mercado Livre fallback."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shopee_agent.competitive_intelligence import CompetitiveIntelligence

ci = CompetitiveIntelligence(path='reports/competitive_offers.jsonl')

# Test ML search directly
items = ci._search_mercadolivre("Smartwatch Xiaomi Band 8", max_items=3)
print(f'ML items: {len(items)}')
if items:
    for r in items[:3]:
        title = r.get("title", "?")
        price = float(r.get("price", 0))
        seller = r.get("seller", {}).get("nickname", "?")
        print(f'  - {title[:50]} R${price:.2f} ({seller})')

# Test full scraper with test items
test_items = [{'item_name': 'Smartwatch Xiaomi Band 8 Pro', 'item_id': 'test001', 'price': 15000}]
count = ci.scrape_competitors(our_items=test_items, max_per_item=3)
print(f'\nOffers scraped: {count}')

snap = ci.snapshot()
print(f'Total offers: {snap.total_offers}')
if snap.total_offers > 0:
    print(f'Threats: {snap.threat_count}, Opps: {snap.opportunity_count}')
    if snap.threats:
        print(f'Threat: {json.dumps(snap.threats[0], ensure_ascii=False)[:200]}')
    if snap.opportunities:
        print(f'Opp: {json.dumps(snap.opportunities[0], ensure_ascii=False)[:200]}')
