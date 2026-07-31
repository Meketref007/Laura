"""CDP - navigate directly to API URL and get content."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

r = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r.json()
ws_url = tab.get("webSocketDebuggerUrl", '')

ws_conn = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
ws_conn.settimeout(10)

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
        except:
            continue

cdp("Page.enable")

# Navigate directly to search API URL
api_url = 'https://shopee.com.br/api/v4/search/search_items?by=relevancy&keyword=Xiaomi%20Band%208&limit=3&newest=0&order=desc&page_type=search&version=2'
cdp("Page.navigate", {"url": api_url})
print("Waiting 5s...")
time.sleep(5)

# Drain
ws_conn.settimeout(0.5)
while True:
    try: ws_conn.recv()
    except: break
ws_conn.settimeout(10)

# Get body content
result = cdp("Runtime.evaluate", {"expression": "document.body ? document.body.innerText : document.documentElement.innerText", "awaitPromise": False})
inner = result.get("result", {}).get("result", {})
content = inner.get("value", "")
print(f'Content length: {len(content)}')
if content:
    # Check if it's JSON or HTML
    print(f'First 500 chars: {content[:500]}')

# Also check what Content-Type the page received
result2 = cdp("Runtime.evaluate", {"expression": "document.contentType || 'unknown'", "awaitPromise": False})
inner2 = result2.get("result", {}).get("result", {})
print(f'Content-Type: {inner2.get("value", "?")}')

ws_conn.close()
