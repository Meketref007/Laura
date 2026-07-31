"""Test CDP scraping with proper message handling."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

# Check CDP available
r = req.get("http://127.0.0.1:9222/json/version", timeout=5)
print(f'CDP version: HTTP {r.status_code}')

# Open new tab
r2 = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r2.json()
ws_url = tab.get("webSocketDebuggerUrl", '')
print(f'WS URL: {ws_url[:60]}...')

ws_conn = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

msg_id = 0
def cdp(method, params=None):
    global msg_id
    msg_id += 1
    msg = json.dumps({"id": msg_id, "method": method, "params": params or {}})
    ws_conn.send(msg)
    # Read until we get the response with our id
    while True:
        raw = ws_conn.recv()
        try:
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
            # else it's an event, ignore
        except json.JSONDecodeError:
            continue

cdp("Page.enable")
print('Page enabled')

cdp("Page.navigate", {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"})
print('Navigated, waiting 5s...')
time.sleep(5)

# Try fetch via CDP with proper error handling
api_url = 'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2'
js = """
(async () => {
    try {
        const r = await fetch('""" + api_url + """', {
            credentials: 'include',
            headers: { 'Accept': 'application/json', 'Referer': 'https://shopee.com.br/search?keyword=Xiaomi+Band+8' }
        });
        const text = await r.text();
        return JSON.stringify({status: r.status, body: text.substring(0, 3000)});
    } catch(e) {
        return JSON.stringify({error: e.message, stack: e.stack});
    }
})()
"""
result = cdp("Runtime.evaluate", {"expression": js, "awaitPromise": True})
print(f'Evaluate result:')

if result and "result" in result:
    val = result["result"].get("value", "{}")
    print(f'  Value type: {type(val).__name__}')
    data = json.loads(val) if isinstance(val, str) else val
    if "error" in data:
        print(f'  Error: {data["error"]}')
    elif "status" in data:
        print(f'  HTTP {data["status"]}')
        if data["status"] == 200:
            body = json.loads(data["body"])
            items = body.get("items", [])
            print(f'  Items: {len(items)}')
            for entry in items[:3]:
                item = entry.get("item_basic", entry)
                print(f'  - {item.get("name","?")[:50]} - R${float(item.get("price",0))/100000:.2f}')
        else:
            print(f'  Body: {data["body"][:500]}')
    else:
        print(f'  Response: {json.dumps(data, ensure_ascii=False)[:500]}')
else:
    print(f'  Raw: {json.dumps(result, ensure_ascii=False)[:500]}')

ws_conn.close()
