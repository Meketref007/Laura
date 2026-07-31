"""CDP - wait longer and check page state."""
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
print("Waiting 10s for full page load...")
time.sleep(10)

# Drain events
ws_conn.settimeout(0.5)
drained = 0
while True:
    try:
        raw = ws_conn.recv()
        drained += 1
    except:
        break
print(f"Drained {drained} events")

ws_conn.settimeout(10)

# Now check state
r1 = cdp("Runtime.evaluate", {"expression": "document.title", "awaitPromise": False})
print(f"Title: {r1.get('result',{}).get('value','?')}")

r2 = cdp("Runtime.evaluate", {"expression": "window.location.href", "awaitPromise": False})
print(f"URL: {r2.get('result',{}).get('value','?')}")

r3 = cdp("Runtime.evaluate", {"expression": "document.readyState", "awaitPromise": False})
print(f"ReadyState: {r3.get('result',{}).get('value','?')}")

r4 = cdp("Runtime.evaluate", {"expression": "document.body ? document.body.innerText.substring(0, 300) : 'no body'", "awaitPromise": False})
print(f"Body: {r4.get('result',{}).get('value','?')[:300]}")

# Check cookies in browser context
r5 = cdp("Runtime.evaluate", {"expression": "document.cookie.substring(0, 500)", "awaitPromise": False})
print(f"Cookies: {r5.get('result',{}).get('value','?')[:200]}")

# Check local storage / session storage
r6 = cdp("Runtime.evaluate", {"expression": "typeof window.__INITIAL_STATE__ !== 'undefined' ? 'found' : 'not found'", "awaitPromise": False})
print(f"__INITIAL_STATE__: {r6.get('result',{}).get('value','?')}")

ws_conn.close()
