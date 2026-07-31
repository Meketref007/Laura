"""Check iframe content."""
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

# List all iframes
r = send("Runtime.evaluate", {"expression": """() => { const frames = document.querySelectorAll('iframe, frame'); const info = []; for (const f of frames) { info.push({src: (f.src || '').substring(0,100), id: f.id, cls: (f.className||'').substring(0,40)}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Iframes in page: {val}")

# Check if there's a specific content container
r = send("Runtime.evaluate", {"expression": """() => { const containers = document.querySelectorAll('[class*="content"], [class*="Content"], [class*="main"], [class*="Main"], [class*="container"], [class*="Container"], [class*="body"], [class*="app"], [class*="App"], [class*="root"], [class*="Root"], [class*="layout"], [class*="Layout"]'); const info = []; for (const c of containers) { if (c.textContent.length > 100) info.push({cls: (c.className||'').substring(0,50), textLen: c.textContent.length}); } return JSON.stringify(info.slice(0,10)); }()""", "returnByValue": True})
val2 = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Large containers: {val2}")

# Check what the iframe content looks like
r = send("Runtime.evaluate", {"expression": """() => { const frame = document.querySelector('iframe'); if (!frame) return 'no iframe'; try { const doc = frame.contentDocument || frame.contentWindow.document; return doc.body.innerText.substring(0, 1000); } catch(e) { return 'iframe error: ' + e.message; } }()""", "returnByValue": True})
val3 = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Iframe content: {val3[:500]}")

# Also check the outerHTML for clues about what 'Envio' looks like
r = send("Runtime.evaluate", {"expression": """() => { const html = document.documentElement.outerHTML; const idx = html.toLowerCase().indexOf('envio'); if (idx >= 0) return html.substring(Math.max(0,idx-200), idx+300); return 'not found'; }()""", "returnByValue": True})
val4 = ((r.get("result") or {}).get("value", "") if r else "")
print(f"HTML around 'Envio':\n{val4}")

sock.close()
