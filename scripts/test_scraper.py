"""Test Shopee search API and competitor scraper."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

# Test Shopee search API directly
url = 'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Smartwatch%20Xiaomi%20Band%208%20Pro&limit=5&newest=0&order=desc&page_type=search&version=2'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://shopee.com.br/',
}
r = requests.get(url, headers=headers, timeout=15)
print(f'Shopee Search API: HTTP {r.status_code}')
if r.status_code == 200:
    data = r.json()
    items = data.get('items', [])
    print(f'Items found: {len(items)}')
    if items:
        for i, entry in enumerate(items[:3]):
            item = entry.get('item_basic', entry)
            name = item.get('name', '?')
            price = float(item.get('price', 0)) / 100000
            location = item.get('shop_location', '?')
            print(f'  {i+1}. {name[:50]} - R${price:.2f} - {location}')
    else:
        print(f'Response preview: {json.dumps(data, indent=2, ensure_ascii=False)[:800]}')
else:
    print(f'Error response: {r.text[:500]}')

# Now test the scraper
print('\n--- Testing CompetitiveIntelligence scraper ---')
from shopee_agent.competitive_intelligence import CompetitiveIntelligence
ci = CompetitiveIntelligence(path='reports/competitive_offers.jsonl')
items = [{'item_name': 'Smartwatch Xiaomi Band 8 Pro', 'item_id': 'test001', 'price': 15000}]
count = ci.scrape_competitors(our_items=items, max_per_item=3)
print(f'Offers recorded: {count}')
snap = ci.snapshot()
print(f'Snapshot: total={snap.total_offers}, threats={snap.threat_count}, opps={snap.opportunity_count}')
if snap.threats:
    print(f'Threat: {json.dumps(snap.threats[0], ensure_ascii=False)[:200]}')
