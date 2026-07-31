"""Test ML API directly."""
import json, requests
r = requests.get(
    'https://api.mercadolibre.com/sites/MLB/search?q=Xiaomi+Band+8&limit=3',
    timeout=15,
    headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
)
print(f'HTTP {r.status_code}')
if r.status_code == 200:
    data = r.json()
    results = data.get('results', [])
    print(f'Results: {len(results)}')
    for x in results[:3]:
        if 'price' in x:
            print(f'  {x.get("title","?")[:50]} R${x.get("price",0):.2f}')
    if not results:
        print(f'Keys: {list(data.keys())}')
        print(f'Paging: {json.dumps(data.get("paging",{}), ensure_ascii=False)}')
        print(f'First 500: {json.dumps(data, ensure_ascii=False)[:500]}')
else:
    print(f'Error: {r.text[:300]}')
