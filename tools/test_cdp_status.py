"""Check product page via CDP with SPA init."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = resp.json()
ws_url = tab.get("webSocketDebuggerUrl", "")

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

# SPA init: navigate to home first
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(5)

# Then product
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(8)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"URL: {url}")

# Click Envio tab
r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a,button,div,span,li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return e.tagName + ' ' + e.textContent.trim(); } } return 'not found'; })()""", "returnByValue": True})
tab_click = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Envio tab click: {tab_click}")
time.sleep(3)

# Check logistics state
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; const isClose = toggle ? toggle.classList.contains('eds-switch--close') : false; info.push({text: text.substring(0,50), toggleClass: toggle ? toggle.className : 'none', isOpen: isOpen, isClose: isClose}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics state: {val}")

# Check save buttons
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('button'); const info = []; for (const b of btns) { info.push({text: b.textContent.trim().substring(0,40), cls: (b.className || '').substring(0,60)}); } return JSON.stringify(info); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Buttons: {val2}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
