"""CDP - fix result parsing."""
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
cdp("Page.navigate", {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"})
print("Waiting 10s...")
time.sleep(10)
# Drain
ws_conn.settimeout(0.5)
while True:
    try: ws_conn.recv()
    except: break
ws_conn.settimeout(10)

r1 = cdp("Runtime.evaluate", {"expression": "document.title", "awaitPromise": False})
result = r1.get("result", {})
inner = result.get("result", {})
print(f"Title: {inner.get('value', 'N/A')}")
print(f"Raw: {json.dumps(r1, ensure_ascii=False)[:500]}")

r2 = cdp("Runtime.evaluate", {"expression": "window.location.href", "awaitPromise": False})
href = r2.get("result", {}).get("result", {}).get("value", "N/A")
print(f"URL: {href}")

r3 = cdp("Runtime.evaluate", {"expression": "document.readyState", "awaitPromise": False})
state = r3.get("result", {}).get("result", {}).get("value", "N/A")
print(f"ReadyState: {state}")

ws_conn.close()
