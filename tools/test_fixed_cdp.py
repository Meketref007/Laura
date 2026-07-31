"""Fixed CDP helper with proper response handling."""
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
        raw = sock.recv()
        data = json.loads(raw)
        if data.get("id") == mid:
            # Return the full data dict for the caller to navigate
            return data
        # skip non-matching events

def eval_js(expr):
    """Evaluate JS and return the result value."""
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner:
            print(f"JS EXCEPTION: {inner['exceptionDetails']}")
            return None
        r = inner.get("result", {})
        return r.get("value")
    return None

def click_element(selector):
    """Click an element by CSS selector."""
    return eval_js(f"document.querySelector('{selector}')?.click(); true")

resp = send("Runtime.enable")
print(f"Runtime.enable: {'OK' if resp else 'FAIL'}")

# Now evaluate
title = eval_js("document.title")
print(f"Title: {title}")

url = eval_js("window.location.href")
print(f"URL: {url[:100]}")

# Check body text
body = eval_js("document.body.innerText.substring(0, 2000)")
print(f"\nBody:\n{body}")

# Check logistics items
logistics = eval_js("""() => { const items = document.querySelectorAll('.logistics-item'); return JSON.stringify(Array.from(items).map(i => ({text: i.textContent.trim().substring(0,60), open: i.querySelector('.eds-switch--open') !== null}))); }()""")
print(f"\nLogistics: {logistics}")

# Check if we can find Envio tab elements
envio = eval_js("""() => { const all = document.querySelectorAll('a, button, div[role=tab], span'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { return 'FOUND: ' + e.tagName + ' visible=' + (e.offsetParent !== null); } } return 'NOT FOUND'; }()""")
print(f"Envio tab: {envio}")

sock.close()
