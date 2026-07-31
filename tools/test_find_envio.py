"""Find where 'Envio' text actually lives in the page."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    if "/portal/product" in t.get("url", ""):
        target = t; break
if not target:
    print("Tab not found"); sys.exit(1)

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

# Search for 'Envio' in the entire raw HTML
r = send("Runtime.evaluate", {"expression": "document.documentElement.outerHTML.includes('Envio') || document.documentElement.outerHTML.includes('envio')", "returnByValue": True})
has = ((r.get("result") or {}).get("value", False) if r else False)
print(f"Envio in HTML: {has}")

# Search for 'Envio' in innerText of ALL elements (not just body)
r = send("Runtime.evaluate", {"expression": "document.documentElement.innerText.includes('Envio')", "returnByValue": True})
has2 = ((r.get("result") or {}).get("value", False) if r else False)
print(f"Envio in doc innerText: {has2}")

# Search for 'Envio' in all text nodes in the document
r = send("Runtime.evaluate", {"expression": """() => { const results = []; const iter = document.createNodeIterator(document, 4); let n; while (n = iter.nextNode()) { const t = n.textContent.trim(); if (t === 'Envio' || t === 'envio') { results.push(n.parentElement.tagName + '.' + (n.parentElement.className||'').substring(0,30)); } } return JSON.stringify(results.slice(0,10)); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Text node matches: {val}")

# Search for 'Env' partial matches
r = send("Runtime.evaluate", {"expression": """() => { const results = []; const iter = document.createNodeIterator(document, 4); let n; while (n = iter.nextNode()) { const t = n.textContent.trim(); if (t.toLowerCase().startsWith('env')) { results.push(t.substring(0,20) + ' | parent=' + n.parentElement.tagName + '.' + (n.parentElement.className||'').substring(0,30)); if (results.length >= 5) break; } } return JSON.stringify(results); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"'Env' matches: {val2}")

# Check if page is inside a frame/iframe
r = send("Runtime.evaluate", {"expression": "window.frames.length", "returnByValue": True})
frames = ((r.get("result") or {}).get("value", -1) if r else -1)
print(f"Iframes: {frames}")

# Check for shadow roots
r = send("Runtime.evaluate", {"expression": """() => { let count = 0; const all = document.querySelectorAll('*'); for (const el of all) { if (el.shadowRoot) count++; } return count; }()""", "returnByValue": True})
shadow = ((r.get("result") or {}).get("value", -1) if r else -1)
print(f"Shadow roots: {shadow}")

sock.close()
