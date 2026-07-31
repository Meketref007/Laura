"""Debug Envio tab finding - broader search."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    if "/portal/product" in t.get("url", ""):
        target = t
        break
if not target:
    print("Product tab not found")
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
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(5)
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(8)

# Search for 'envio' text in all elements (even deeply nested)
r = send("Runtime.evaluate", {"expression": """() => { const results = []; const walker = document.createTreeWalker(document.body, 4, null, false); let n; while (n = walker.nextNode()) { if (n.textContent.trim().toLowerCase() === 'envio') { let el = n; for (let i = 0; i < 5; i++) { el = el.parentElement; if (!el) break; results.push('depth=' + i + ' tag=' + el.tagName + ' cls=' + (el.className||'').substring(0,40)); } break; } } return JSON.stringify(results); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Envio text node parents: {val}")

# Search for 'envio' in all attributes
r = send("Runtime.evaluate", {"expression": """() => { const results = []; const all = document.querySelectorAll('*'); for (const el of all) { const a = el.getAttribute('aria-label'); if (a && a.toLowerCase().includes('envio')) { results.push('aria-label=' + a + ' tag=' + el.tagName + ' cls=' + (el.className||'').substring(0,40)); } } return JSON.stringify(results); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Aria-label envio: {val2}")

# Search for eds-tabs (Shopee tab component)
r = send("Runtime.evaluate", {"expression": """() => { const tabs = document.querySelectorAll('.eds-tabs__nav-tab, [class*="tab"], [class*="Tab"]'); const info = []; for (const t of tabs) { info.push({text: t.textContent.trim().substring(0,30), cls: (t.className||'').substring(0,60)}); } return JSON.stringify(info); }()""", "returnByValue": True})
val3 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Tab elements: {val3}")

# Just dump the inner HTML of the tab navigation area
r = send("Runtime.evaluate", {"expression": """() => { const nav = document.querySelector('.eds-tabs__nav, [class*="tabs__nav"], [class*="Tabs__nav"]'); if (nav) return nav.innerHTML.substring(0, 2000); const all = document.querySelectorAll('*'); for (const el of all) { if (el.children.length >= 5 && ['Informação básica','Especificação','Descrição'].every(t => el.textContent.includes(t))) { return el.innerHTML.substring(0, 2000); } } return 'not found'; }()""", "returnByValue": True})
val4 = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Tab navigation HTML: {val4[:1000]}")

sock.close()
