"""Inspect existing product page tab - check Envio tab content and save button."""
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

# Click Envio tab
send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a,button,div,span,li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return 'ok'; } } return 'not found'; })()""", "returnByValue": True})
time.sleep(4)

# Check logistics after clicking Envio
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics after Envio click: {val}")

# Check all buttons
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('button, [role="button"], .eds-btn, .eds-button'); const info = []; for (const b of btns) { info.push({tag: b.tagName, text: b.textContent.trim().substring(0,40), cls: (b.className || '').substring(0,60), type: b.getAttribute('type') || ''}); } return JSON.stringify(info); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Buttons: {val2}")

# Check if there's any "salvar" text on page
r = send("Runtime.evaluate", {"expression": "document.body.innerText.includes('Salvar') || document.body.innerText.includes('salvar')", "returnByValue": True})
has_save = ((r.get("result") or {}).get("value", False) if r else False)
print(f"Has 'salvar' text: {has_save}")

# Check all elements with text containing 'salvar'
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); const found = []; for (const el of all) { if (el.children.length === 0 && el.textContent.trim().toLowerCase().includes('salvar')) { found.push(el.tagName + ' ' + (el.className || '').substring(0,40)); } } return JSON.stringify(found); }()""", "returnByValue": True})
val3 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Elements with 'salvar': {val3}")

# Check for auto-save indicator
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); const auto = []; for (const el of all) { const t = el.textContent.trim().toLowerCase(); if (t.includes('salvo') || t.includes('auto') || t.includes('autom')) { auto.push(el.tagName + ' ' + t.substring(0,40)); } } return JSON.stringify(auto); }()""", "returnByValue": True})
val4 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Auto-save indicators: {val4}")

sock.close()
