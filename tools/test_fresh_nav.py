"""Navigate existing tab to fresh product page and check Envio tab."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    if "/portal/product/58256032299" in t.get("url", ""):
        target = t
        break
if not target:
    print("Tab not found")
    sys.exit(1)

ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
msg_id = 0
def send(m, p=None):
    global msg_id; msg_id += 1
    sock.send(json.dumps({"id": msg_id, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == msg_id: return data.get("result")

send("Page.enable")

# Navigate to home first (SPA init), then product
print("Navigating to home...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(5)

print("Navigating to product...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(8)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"URL: {url}")

# Check body content
r = send("Runtime.evaluate", {"expression": "document.body.innerText.substring(0, 2000)", "returnByValue": True})
body = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Body preview: {body[:500]}")

# Look for Envio tab
r = send("Runtime.evaluate", {"expression": """() => { const els = document.querySelectorAll('a,button,div,span,li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { return e.tagName + '|' + e.className.substring(0,60) + '|visible=' + (e.offsetParent !== null); } } return 'not found'; }()""", "returnByValue": True})
tab_info = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Envio tab: {tab_info}")

# Click Envio
send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a,button,div,span,li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""", "returnByValue": True})
time.sleep(4)

# Check logistics
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics: {val}")

# Check for any buttons
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('button'); const info = []; for (const b of btns) { info.push(b.textContent.trim().substring(0,30)); } return JSON.stringify(info); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Buttons: {val2}")

sock.close()
