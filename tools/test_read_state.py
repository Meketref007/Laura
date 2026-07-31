"""Read current toggle state from EXISTING tab WITHOUT navigating."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

# Find existing product tab - DON'T navigate, just read state
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    if "/portal/product" in t.get("url", ""):
        target = t; print(f"Found: {t.get('url','')[:80]}"); break
if not target:
    print("No product tab found")
    sys.exit(1)

ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data.get("result")

# DON'T navigate - just check current state
# Check if Envio tab content is already loaded
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Current logistics (no navigation): {val}")

# Try clicking Envio and checking again
r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a, button, div, span, li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return 'clicked'; } } return 'NOT FOUND'; })()""", "returnByValue": True})
click = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"Envio click: {click}")
time.sleep(3)

r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics after Envio click: {val2}")

sock.close()
