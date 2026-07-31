"""Try new tab like the successful test did."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

# Create NEW tab
resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = resp.json()
ws_url = tab.get("webSocketDebuggerUrl", "")

sock = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data.get("result")

send("Page.enable")

# Navigate to home first (SPA init)
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(5)

# Navigate to product
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(8)

# Click Envio tab
r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a, button, div, span, li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return e.tagName + ' ' + e.textContent.trim(); } } return 'not found'; })()""", "returnByValue": True})
click = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Envio click: {click}")
time.sleep(4)

# Check logistics
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics: {val}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
