"""Test CDP scraping directly."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

# Check CDP available
r = req.get("http://127.0.0.1:9222/json/version", timeout=5)
print(f'CDP version: HTTP {r.status_code}')
if r.status_code == 200:
    print(f'Browser: {r.json().get("Browser", "?")}')

# Open new tab
r2 = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r2.json()
ws_url = tab.get("webSocketDebuggerUrl", '')
print(f'New tab WS: {ws_url[:60]}...')

ws_conn = ws.create_connection(ws_url, timeout=20,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

def cdp(method, params=None):
    msg = json.dumps({"id": 1, "method": method, "params": params or {}})
    ws_conn.send(msg)
    raw = ws_conn.recv()
    return json.loads(raw)

cdp("Page.enable")
cdp("Page.navigate", {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"})
print('Navigated to search page, waiting 5s...')
time.sleep(5)

# Try fetch via CDP
js = """
fetch('https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2', {
    credentials: 'include',
    headers: { 'Accept': 'application/json', 'Referer': 'https://shopee.com.br/search?keyword=Xiaomi+Band+8' }
})
.then(r => r.json())
.then(d => JSON.stringify(d))
.catch(e => JSON.stringify({error: e.message}))
"""
result = cdp("Runtime.evaluate", {"expression": js, "awaitPromise": True})
time.sleep(2)

if result and "result" in result:
    val = result["result"].get("value", "{}")
    data = json.loads(val)
    if "error" in data:
        print(f'Fetch error: {data["error"]}')
    elif "items" in data:
        items = data["items"]
        print(f'Items found: {len(items)}')
        for entry in items[:3]:
            item = entry.get("item_basic", entry)
            print(f'  - {item.get("name", "?")[:50]} R${float(item.get("price",0))/100000:.2f}')
        if not items:
            print(f'Response keys: {list(data.keys())}')
            print(f'Response: {json.dumps(data, ensure_ascii=False)[:500]}')
    else:
        print(f'Unexpected response: {json.dumps(data, ensure_ascii=False)[:500]}')
else:
    print(f'CDP result error: {json.dumps(result, ensure_ascii=False)[:300]}')

# Try scraping page HTML via CDP
result2 = cdp("Runtime.evaluate", {"expression": "document.querySelector('script#__NEXT_DATA__')?.textContent || document.querySelector('script[data-initial-state]')?.textContent || document.body.innerText.substring(0,2000)"})
if result2 and "result" in result2:
    val = result2["result"].get("value", "")
    print(f'\nPage content: {val[:300]}')

ws_conn.close()
