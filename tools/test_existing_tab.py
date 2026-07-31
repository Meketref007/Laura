"""Connect to existing product page tab via CDP."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

# Find the product page tab
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    url = t.get("url", "")
    if "/portal/product/58256032299" in url:
        target = t
        break

if not target:
    print("Product page tab not found")
    sys.exit(1)

ws_url = target.get("webSocketDebuggerUrl", "")
print(f"Found tab: {target.get('id','')[:30]}")

# Connect to existing tab
sock = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
msg_id = 0

def send(method, params=None):
    global msg_id
    msg_id += 1
    sock.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = sock.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data.get("result")

send("Page.enable")

# Check body content
r = send("Runtime.evaluate", {"expression": "document.body ? document.body.innerText.substring(0, 3000) : 'no body'", "returnByValue": True})
body = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Body: {body[:500]}")

# Check logistics
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics: {val}")

sock.close()
