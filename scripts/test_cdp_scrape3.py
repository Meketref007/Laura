"""Test CDP scraping - navigate directly to API URL."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

r = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r.json()
ws_url = tab.get("webSocketDebuggerUrl", '')

ws_conn = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

msg_id = 0
def cdp(method, params=None):
    global msg_id
    msg_id += 1
    ws_conn.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = ws_conn.recv()
        try:
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
        except json.JSONDecodeError:
            continue

cdp("Page.enable")
cdp("Network.enable")

# Approach 1: Navigate to search page, then execute XMLHttpRequest
cdp("Page.navigate", {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"})
print('Waiting 5s for page load...')
time.sleep(5)

# Approach 2: Use XMLHttpRequest instead of fetch (may have different CORS behavior)
js_xhr = """
(function() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2', false);
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.setRequestHeader('Referer', 'https://shopee.com.br/search?keyword=Xiaomi+Band+8');
    xhr.withCredentials = true;
    try { xhr.send(null); } catch(e) { return JSON.stringify({error: e.message}); }
    return JSON.stringify({status: xhr.status, body: xhr.responseText.substring(0, 5000)});
})()
"""
result = cdp("Runtime.evaluate", {"expression": js_xhr, "awaitPromise": False})
val = result.get("result", {}).get("value", "{}")
data = json.loads(val)
print(f'XHR: status={data.get("status")}, error={data.get("error","")}')
if data.get("status") == 200:
    body = json.loads(data["body"])
    items = body.get("items", [])
    print(f'  Items: {len(items)}')
    for entry in items[:3]:
        item = entry.get("item_basic", entry)
        print(f'  - {item.get("name","?")[:50]}')

# Approach 3: Navigate directly to API URL
print('\nTrying direct navigation to API URL...')
cdp("Page.navigate", {"url": "https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2"})
time.sleep(3)
result3 = cdp("Runtime.evaluate", {"expression": "document.body.innerText.substring(0, 5000)"})
val3 = result3.get("result", {}).get("value", "")
print(f'Direct API: {val3[:300]}')

# Approach 4: Check what cookies are available
result_cookies = cdp("Runtime.evaluate", {"expression": "document.cookie.substring(0, 500)"})
val_c = result_cookies.get("result", {}).get("value", "")
print(f'\nCookies: {val_c[:200]}')

ws_conn.close()
