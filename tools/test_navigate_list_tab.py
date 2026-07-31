"""Navigate existing product list tab (with valid session) to specific product."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

# Find the product list tab (still has valid session)
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    if "product/list" in t.get("url", ""):
        target = t
        print(f"Using tab: {t.get('id','')[:20]} | {t.get('url','')[:80]}")
        break
if not target:
    print("No product list tab found")
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

send("Page.enable")
send("Runtime.enable")

PRODUCT_ID = "58256032299"
url = f"https://seller.shopee.com.br/portal/product/{PRODUCT_ID}/edit"

# Navigate
print(f"Navigating to: {url}")
send("Page.navigate", {"url": url})
time.sleep(8)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
curr_url = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Current URL: {curr_url[:100]}")

if "login" in curr_url.lower():
    print("REDIRECTED TO LOGIN - session also expired on list tab!")
    sock.close()
    sys.exit(1)

# Check page body
r = send("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
title = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"Title: {title}")

# Find and click "Envio" tab
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('a, button, div[role=tab], li, span[class*=tab]'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.scrollIntoView(); e.click(); return 'CLICKED ' + e.tagName; } } return 'NOT FOUND'; }()""", "returnByValue": True})
click = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"Envio click: {click}")
time.sleep(3)

# Check logistics items
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; const spi = item.closest('[class*=shipping]') || item.closest('[class*=logistics]'); info.push({text: text.substring(0,80), isOpen: isOpen, channelSel: spi ? 'yes' : 'no'}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics items: {val}")

# Also: check all visible text for "envio" or "correios"
r = send("Runtime.evaluate", {"expression": "document.body.innerText.substring(0,3000)", "returnByValue": True})
body = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Body text:\n{body}")

sock.close()
