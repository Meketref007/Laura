"""Simple CDP test - navigate and get title."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

r = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r.json()
ws_url = tab.get("webSocketDebuggerUrl", '')

ws_conn = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

# Set timeout on recv
ws_conn.settimeout(10)

msg_id = 0
def cdp(method, params=None):
    global msg_id
    msg_id += 1
    msg = json.dumps({"id": msg_id, "method": method, "params": params or {}})
    ws_conn.send(msg)
    while True:
        raw = ws_conn.recv()
        try:
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
        except:
            continue

cdp("Page.enable")
print("1. Page enabled")

cdp("Page.navigate", {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"})
print("2. Navigated")

time.sleep(5)

result = cdp("Runtime.evaluate", {"expression": "document.title", "awaitPromise": False})
print(f"3. Title: {result.get('result', {}).get('value', 'NO TITLE')}")

result2 = cdp("Runtime.evaluate", {"expression": "document.body ? document.body.innerText.substring(0, 100) : 'no body'", "awaitPromise": False})
print(f"4. Body: {result2.get('result', {}).get('value', 'N/A')[:100]}")

result3 = cdp("Runtime.evaluate", {"expression": "document.readyState", "awaitPromise": False})
print(f"5. ReadyState: {result3.get('result', {}).get('value', 'N/A')}")

ws_conn.close()
print("6. Done")
