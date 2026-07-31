"""Click Envio tab and toggle shipping channel."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "/portal/product/" in t.get("url","") and "list" not in t.get("url","")), None)
if not target:
    # Navigate from product list
    target = next((t for t in tabs if "product/list" in t.get("url","")), None)
    ws_url = target.get("webSocketDebuggerUrl", "")
    sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
    mid = 0
    def send(m, p=None):
        global mid; mid += 1
        sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
        while True:
            raw = sock.recv(); data = json.loads(raw)
            if data.get("id") == mid: return data
    send("Page.enable")
    send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
    time.sleep(6)
else:
    ws_url = target.get("webSocketDebuggerUrl", "")
    sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
    mid = 0
    def send(m, p=None):
        global mid; mid += 1
        sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
        while True:
            raw = sock.recv(); data = json.loads(raw)
            if data.get("id") == mid: return data
    send("Page.enable")

send("Runtime.enable")

def eval_js(expr):
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner: return None
        return inner.get("result", {}).get("value")
    return None

url = eval_js("window.location.href")
print(f"On URL: {url[:80] if url else '?'}")

if not url or "product" not in url:
    print("Not on product page!")
    sock.close()
    sys.exit(1)

# Click Envio tab
print("\nClicking Envio tab...")
envio_clicked = eval_js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.scrollIntoView(); e.click(); return e.tagName + ' visible=' + (e.offsetParent !== null); } } return 'NOT FOUND'; })()""")
print(f"Envio click: {envio_clicked}")
time.sleep(4)

# Check logistics items
logistics = eval_js("document.querySelectorAll('.logistics-item').length")
print(f"Logistics items: {logistics}")

# Get the full text of the envio section
envio_section = eval_js("""(() => { const all = document.querySelectorAll('*'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { const parent = e.closest('[class*=tab], [class*=panel], [class*=content], section, div') || e.parentElement; return (parent?.textContent || '').trim().substring(0, 3000); } } return ''; })()""")
print(f"Envio section:\n{envio_section}")

# Also check if there are any switches
switches = eval_js("document.querySelectorAll('.eds-switch').length")
print(f"\nEDS switches: {switches}")

# Get details of switches
switch_info = eval_js("""Array.from(document.querySelectorAll('.eds-switch')).map(s => ({open: s.classList.contains('eds-switch--open'), parentText: (s.closest('[class*=logistics], [class*=shipping], [class*=item], tr, div')?.textContent || '').trim().substring(0,60)})).slice(0,10)""")
print(f"Switches: {switch_info}")

sock.close()
