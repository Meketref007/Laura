"""Test CDP with cookie injection from JSON file."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

# Load cookies from JSON
from shopee_agent.seller_center import load_cookies
session = load_cookies()
if not session:
    print("No cookies loaded")
    sys.exit(1)

print(f"Loaded {len(session.cookies)} cookies, valid={session.is_valid()}")

# Create new tab
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

# Inject cookies before navigating
print("Injecting cookies...")
for c in session.cookies:
    if c.is_expired():
        continue
    params = {
        "name": c.name,
        "value": c.value,
        "domain": c.domain,
        "path": c.path,
        "secure": c.secure,
        "httpOnly": c.httpOnly,
    }
    if c.expirationDate:
        params["expires"] = c.expirationDate
    send("Network.setCookie", params)

print("Cookies injected")

# Now navigate
send("Page.enable")
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(6)
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(10)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"URL: {url}")

# Click Envio
r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a, button, div, span, li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return 'ok'; } } return 'NOT FOUND'; })()""", "returnByValue": True})
print(f"Envio click: {((r.get('result') or {}).get('value', '?') if r else '?')}")
time.sleep(4)

# Check logistics
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics: {val}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
