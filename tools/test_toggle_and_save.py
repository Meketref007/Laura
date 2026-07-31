"""Toggle shipping channel and verify persistence."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "/portal/product/" in t.get("url","") and "list" not in t.get("url","")), None)
if not target:
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

# Navigate to product page and click Envio
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(6)
eval_js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

# Get initial state
initial = eval_js("""Array.from(document.querySelectorAll('.eds-switch')).map((s, i) => ({idx: i, open: s.classList.contains('eds-switch--open')}))""")
print(f"Initial state: {initial}")

# Get more context about the switches
switch_context = eval_js("""Array.from(document.querySelectorAll('.eds-switch')).map((s, i) => { const parent = s.parentElement; const gp = parent?.parentElement; const ggp = gp?.parentElement; return {idx: i, open: s.classList.contains('eds-switch--open'), parentClass: (parent?.className||'').substring(0,40), parentTag: parent?.tagName || '?', gpClass: (gp?.className||'').substring(0,40), gpText: (gp?.textContent||'').trim().substring(0,60)}; })""")
print(f"Switch context: {switch_context}")

# Click the closed switch to OPEN it (index 0 is closed currently)
print("\nClicking switch[0] (closed -> open)...")
eval_js("document.querySelectorAll('.eds-switch')?.[0]?.click()")
time.sleep(3)

# Check state after click
after = eval_js("""Array.from(document.querySelectorAll('.eds-switch')).map((s, i) => ({idx: i, open: s.classList.contains('eds-switch--open')}))""")
print(f"After click: {after}")

# Check for save button
save_btn = eval_js("""() => { const btns = document.querySelectorAll('button, a, [role=button]'); const found = []; for (const b of btns) { const txt = b.textContent.trim().toLowerCase(); if (txt.includes('salvar') || txt.includes('save') || txt.includes('aplicar') || txt.includes('confirmar')) { found.push({text: b.textContent.trim().substring(0,30), cls: (b.className||'').substring(0,30)}); } } return JSON.stringify(found); }()""")
print(f"Save buttons: {save_btn}")

# Also check for toast/notification
toast = eval_js("""() => { const all = document.querySelectorAll('*'); for (const e of all) { if ((e.textContent || '').includes('salvo') || (e.textContent || '').includes('sucesso') || e.className.includes('toast') || e.className.includes('success')) { return e.tagName + ' ' + (e.className||'').substring(0,30) + ' ' + (e.textContent||'').trim().substring(0,100); } } return 'none found'; }()""")
print(f"Toast: {toast}")

sock.close()
