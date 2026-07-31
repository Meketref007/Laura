"""Test full toggle flow - click toggle, then save, verify state changed."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

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

send("Page.enable")

# Navigate to home first
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(6)

# Navigate to product
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(10)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"URL: {url}")

# Click Envio tab
r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a, button, div, span, li'); for (const e of els) { const t = e.textContent.trim().toLowerCase(); if (t === 'envio' || t === 'envio ') { e.click(); return e.tagName + ' ' + e.textContent.trim(); } } return 'NOT FOUND'; })()""", "returnByValue": True})
click = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Envio click: {click}")
time.sleep(4)

# Check logistics
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics: {val}")

# If found, try toggling
if val and val != "[]":
    parsed = json.loads(val)
    for item in parsed:
        text = item.get("text", "").lower()
        if "retirada" in text:
            print(f"Found Retirada: isOpen={item.get('isOpen')}")
            if not item.get("isOpen"):
                # Click the toggle
                r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); for (const item of items) { if (item.textContent.toLowerCase().includes('retirada')) { const toggle = item.querySelector('.eds-switch'); if (toggle) { toggle.click(); return 'clicked'; } } } return 'not found'; }()""", "returnByValue": True})
                click_result = ((r.get("result") or {}).get("value", "") if r else "")
                print(f"Toggle click: {click_result}")
                time.sleep(2)
                
                # Check state after toggle
                r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); for (const item of items) { if (item.textContent.toLowerCase().includes('retirada')) { const toggle = item.querySelector('.eds-switch'); return toggle ? toggle.className : 'no toggle'; } } return 'not found'; }()""", "returnByValue": True})
                after = ((r.get("result") or {}).get("value", "") if r else "")
                print(f"After toggle: {after}")
                
                # Try to find save button
                r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); const found = []; for (const el of all) { if (el.children.length === 0 && el.textContent.trim().toLowerCase().includes('salvar')) { found.push(el.tagName + ' ' + (el.className||'').substring(0,60)); } } return JSON.stringify(found); }()""", "returnByValue": True})
                save = ((r.get("result") or {}).get("value", "[]") if r else "[]")
                print(f"Salvar elements: {save}")
                
                # Check all interactive elements
                r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('button, [type="submit"], [role="button"], .eds-btn'); const info = []; for (const b of btns) { info.push({tag: b.tagName, text: b.textContent.trim().substring(0,40), cls: (b.className||'').substring(0,60)}); } return JSON.stringify(info); }()""", "returnByValue": True})
                btns = ((r.get("result") or {}).get("value", "[]") if r else "[]")
                print(f"Interactive: {btns}")
            break

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
