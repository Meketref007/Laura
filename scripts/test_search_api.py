"""Test different approaches for Shopee search."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
load_dotenv()

session = requests.Session()

# Try with SPID cookie from env
spid_cookie = os.getenv('LAURA_CDP_COOKIES', '')
cookies = {}
if spid_cookie:
    try:
        from shopee_agent.seller_center import load_cookies
        cj = load_cookies()
        if cj:
            for c in cj:
                if c.domain and ('shopee' in c.domain or c.domain == '.shopee.com.br'):
                    session.cookies.set(c.name, c.value, domain=c.domain)
                    cookies[c.name] = c.value[:10] + '...'
    except:
        pass

print(f'Loaded {len(cookies)} Shopee cookies')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://shopee.com.br/',
    'Accept': 'application/json',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Origin': 'https://shopee.com.br',
    'X-Requested-With': 'XMLHttpRequest',
}

# Approach 1: Search API with cookies
url1 = 'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2'
r1 = session.get(url1, headers=headers, timeout=15)
print(f'\n1. API com cookies: HTTP {r1.status_code}')
if r1.status_code == 200:
    items = r1.json().get('items', [])
    print(f'   Items: {len(items)}')
    if items:
        for entry in items[:2]:
            item = entry.get('item_basic', entry)
            print(f'   - {item.get("name","?")[:50]}')
else:
    err = r1.json() if r1.text.startswith('{') else r1.text[:200]
    print(f'   Error: {json.dumps(err)[:200] if isinstance(err, dict) else err}')

# Approach 2: Search suggestion API (often more permissive)
url2 = 'https://shopee.com.br/api/v4/search/search_suggest?keyword=Xiaomi%20Band&limit=3'
r2 = session.get(url2, headers=headers, timeout=15)
print(f'\n2. Suggest API: HTTP {r2.status_code}')
if r2.status_code == 200:
    print(f'   {json.dumps(r2.json(), ensure_ascii=False)[:300]}')
else:
    print(f'   {r2.text[:200]}')

# Approach 3: Item search via recommendation API
url3 = 'https://shopee.com.br/api/v4/recommend/recommend?bundle=search_result&keyword=Xiaomi%20Band%208&limit=3'
r3 = session.get(url3, headers=headers, timeout=15)
print(f'\n3. Recommend API: HTTP {r3.status_code}')
if r3.status_code == 200:
    print(f'   {json.dumps(r3.json(), ensure_ascii=False)[:300]}')
else:
    print(f'   {r3.text[:200]}')

# Approach 4: HTML scraping (fallback)
print('\n4. HTML scraping fallback...')
from bs4 import BeautifulSoup
url4 = 'https://shopee.com.br/search?keyword=Xiaomi%20Band%208'
r4 = session.get(url4, headers={**headers, 'Accept': 'text/html,*/*'}, timeout=15)
print(f'   HTTP {r4.status_code}, len={len(r4.text)}')
if r4.status_code == 200:
    soup = BeautifulSoup(r4.text, 'html.parser')
    # Look for product data in script tags
    for script in soup.find_all('script'):
        if 'window.__INITIAL_STATE__' in (script.string or ''):
            print('   Found __INITIAL_STATE__')
            break
    # Count product cards
    cards = soup.select('[data-sqe="item"]') or soup.select('.shopee-search-item-result__item')
    print(f'   Product cards: {len(cards)}')
    if cards:
        print(f'   First: {cards[0].text[:100]}')
    else:
        # Print all script tags
        for s in soup.find_all('script'):
            if s.string and len(s.string) > 100:
                print(f'   Script: {s.string[:200]}')
