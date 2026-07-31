"""Test Shopee search with Seller Center cookies."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopee_agent.seller_center import SellerCenterClient

client = SellerCenterClient()
if not client.is_authenticated():
    print("Not authenticated! Cannot search.")
    exit(1)

s = client._ensure_session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://shopee.com.br/',
    'Accept': 'application/json',
}

url = 'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2'
r = s.get(url, headers=headers, timeout=15)
print(f'Shopee Search with cookies: HTTP {r.status_code}')
if r.status_code == 200:
    data = r.json()
    items = data.get('items', [])
    print(f'Items: {len(items)}')
    if items:
        for entry in items[:3]:
            item = entry.get('item_basic', entry)
            name = item.get('name', '?')
            price = float(item.get('price', 0)) / 100000
            print(f'  - {name[:50]} R${price:.2f}')
    else:
        print(json.dumps(data, ensure_ascii=False)[:500])
else:
    print(f'Error: {r.text[:300]}')
    print('Cookies:')
    for c in s.cookies:
        print(f'  {c.name}={c.value[:15]}...')
