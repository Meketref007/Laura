"""Test ML API with different headers."""
import json, requests
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Origin': 'https://www.mercadolivre.com.br',
    'Referer': 'https://www.mercadolivre.com.br/',
    'x-requested-with': 'XMLHttpRequest',
}
r = requests.get(
    'https://api.mercadolibre.com/sites/MLB/search?q=Xiaomi+Band+8&limit=3',
    timeout=15, headers=headers
)
print(f'HTTP {r.status_code}')
if r.status_code == 200:
    data = r.json()
    results = data.get('results', [])
    print(f'Results: {len(results)}')
    for x in results[:3]:
        if 'price' in x:
            print(f'  {x.get("title","?")[:50]} R${x.get("price",0):.2f}')
else:
    print(f'Error: {r.text[:300]}')

# Try without trailing /sites/MLB
r2 = requests.get(
    'https://api.mercadolibre.com/sites/MLB/search?q=Xiaomi%20Band%208&limit=3&category=MLB1055',
    timeout=15, headers=headers
)
print(f'\nWith category: HTTP {r2.status_code}')
if r2.status_code == 200:
    data = r2.json()
    print(f'Results: {len(data.get("results",[]))}')
else:
    print(f'Error: {r2.text[:200]}')

# Try meli API
r3 = requests.get(
    'https://api.mercadolibre.com/items/MLB123456789',
    timeout=15, headers=headers
)
print(f'\nSingle item: HTTP {r3.status_code}')

# Check what the real website returns
r4 = requests.get(
    'https://www.mercadolivre.com.br/ofertas',
    timeout=15,
    headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'}
)
print(f'\nML homepage: HTTP {r4.status_code}')
if r4.status_code == 200:
    # Check if we get a JS challenge
    if 'captcha' in r4.text.lower() or 'cf-browser-verification' in r4.text:
        print('  Cloudflare challenge detected!')
    else:
        print(f'  HTML length: {len(r4.text)}')
else:
    print(f'  Error: {r4.text[:200]}')
