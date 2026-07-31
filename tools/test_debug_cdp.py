"""Debug CDP communication."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

# List tabs and find a seller center tab
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    url = t.get("url", "")
    if "seller.shopee.com.br" in url and "product/list" in url:
        target = t
        print("Using list tab:", url[:80])
        break
if not target:
    print("No seller list tab, checking any seller tab...")
    for t in tabs:
        url = t.get("url", "")
        if "seller.shopee.com.br" in url:
            target = t; print("Using seller tab:", url[:80]); break
if not target:
    print("Still no seller tab, trying login tab...")
    for t in tabs:
        if "seller/login" in t.get("url",""):
            target = t; print("Using login tab:", url[:80]); break
if not target:
    resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
    target = resp.json()

ws_url = target.get("webSocketDebuggerUrl", "")
print(f"Connecting to WS...")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    req_data = json.dumps({"id": mid, "method": m, "params": p or {}})
    sock.send(req_data)
    while True:
        raw = sock.recv()
        data = json.loads(raw)
        if data.get("id") == mid:
            if "error" in data:
                print(f"CDP ERROR: {data['error']}")
                return None
            return data.get("result")
        # ignore other messages

# Enable DOM
r = send("Runtime.enable")
print(f"Runtime.enable: {'OK' if r else 'FAIL'}")

# Simple eval
r = send("Runtime.evaluate", {"expression": "1+1", "returnByValue": True})
print(f"1+1 = {r.get('value') if r else 'ERROR'}")

# Check document
r = send("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
print(f"Title: {r.get('value') if r else 'ERROR'}")

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href.substring(0,100)", "returnByValue": True})
print(f"URL: {r.get('value') if r else 'ERROR'}")

sock.close()
