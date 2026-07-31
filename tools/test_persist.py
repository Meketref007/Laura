"""Toggle and verify persistence with page reload."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data

def js(expr):
    """Evaluate JS, return value or None."""
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner:
            print(f"  JS Error: {inner['exceptionDetails'].get('text','')}")
            return None
        return inner.get("result", {}).get("value")
    return None

send("Page.enable")
send("Runtime.enable")

PRODUCT_ID = "58256032299"
PRODUCT_URL = f"https://seller.shopee.com.br/portal/product/{PRODUCT_ID}"

# Navigate to product
print("Navigating to product...")
send("Page.navigate", {"url": PRODUCT_URL})
time.sleep(7)

# Click Envio tab
print("Clicking Envio tab...")
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

# Read initial state
initial = js("""JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s, i) { return {idx: i, open: s.classList.contains('eds-switch--open')}; }))""")
print(f"Initial: {initial}")

# Toggle switch[0] (closed -> open)
print("Toggling switch[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(3)

# Read state after toggle
after_toggle = js("""JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s, i) { return {idx: i, open: s.classList.contains('eds-switch--open')}; }))""")
print(f"After toggle: {after_toggle}")

# Check for save button
buttons = js("""(function() { var btns = document.querySelectorAll('button, a, [role=button]'); var found = []; for (var i = 0; i < btns.length; i++) { var b = btns[i]; var txt = b.textContent.trim().toLowerCase(); if (txt.indexOf('salvar') >= 0 || txt.indexOf('save') >= 0 || txt.indexOf('aplicar') >= 0) { found.push({text: b.textContent.trim().substring(0,30), cls: (b.className||'').substring(0,30)}); } } return JSON.stringify(found); })()""")
print(f"Save buttons: {buttons}")

# Wait for any auto-save, then reload
print("Waiting 3s for auto-save...")
time.sleep(3)

# Reload the page to verify persistence
print("Reloading page...")
send("Page.reload")
time.sleep(7)

# Click Envio again
print("Clicking Envio tab after reload...")
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

# Read state after reload
after_reload = js("""JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s, i) { return {idx: i, open: s.classList.contains('eds-switch--open')}; }))""")
print(f"After reload: {after_reload}")

sock.close()
