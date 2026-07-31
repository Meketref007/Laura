"""Scan the page for save-related elements."""
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
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(6)
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(10)

# Search entire HTML for 'salvar', 'save', 'publicar', 'atualizar'
r = send("Runtime.evaluate", {"expression": """() => { const keywords = ['salvar','save','publicar','atualizar','confirmar','aplicar']; const all = document.querySelectorAll('*'); const found = []; for (const el of all) { const t = el.textContent.trim().toLowerCase(); for (const kw of keywords) { if (t.includes(kw) && el.children.length === 0) { found.push({kw: kw, text: t.substring(0,40), tag: el.tagName, cls: (el.className||'').substring(0,40)}); break; } } } return JSON.stringify(found.slice(0,20)); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Save-related elements: {val}")

# Search for any clickable/element with onclick or similar
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('[onclick], [ng-click], [@click], [v-on:click], [data-click]'); const info = []; for (const el of all) { info.push({tag: el.tagName, cls: (el.className||'').substring(0,40), onclick: (el.getAttribute('onclick')||'').substring(0,60)}); } return JSON.stringify(info.slice(0,10)); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Click handlers: {val2}")

# Look for the page footer/action bar
r = send("Runtime.evaluate", {"expression": """() => { const footer = document.querySelector('footer, [class*="footer"], [class*="Footer"], [class*="action-bar"], [class*="ActionBar"], [class*="toolbar"], [class*="Toolbar"]'); if (footer) return footer.textContent.substring(0, 500); return 'no footer found'; }()""", "returnByValue": True})
val3 = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Footer/action bar: {val3[:300]}")

# Check all divs with role="button"
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('[role="button"]'); const info = []; for (const b of btns) { info.push({tag: b.tagName, text: b.textContent.trim().substring(0,30), cls: (b.className||'').substring(0,40)}); } return JSON.stringify(info); }()""", "returnByValue": True})
val4 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Role=button: {val4}")

# Check for all eds-btn elements (Shopee button component)
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('[class*="eds-btn"], [class*="eds-button"]'); const info = []; for (const b of btns) { info.push({text: b.textContent.trim().substring(0,30), cls: (b.className||'').substring(0,60)}); } return JSON.stringify(info); }()""", "returnByValue": True})
val5 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"EDS buttons: {val5}")

# Dump the last 2000 chars of body to find the action area
r = send("Runtime.evaluate", {"expression": "document.body.innerHTML.substring(document.body.innerHTML.length - 3000)", "returnByValue": True})
val6 = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Body tail HTML:\n{val6[:1500]}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
