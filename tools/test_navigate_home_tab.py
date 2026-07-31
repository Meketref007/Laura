"""Navigate from home page to product list -> product edit."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

# Find home tab (not the redirected login tab)
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    url = t.get("url", "")
    if url.rstrip("/") == "https://seller.shopee.com.br" or url.rstrip("/") == "https://seller.shopee.com.br/":
        target = t
        print(f"Found HOME tab: {t.get('id','')[:20]}")
        break
if not target:
    print("No home tab, navigating...")
    # Can't navigate without a valid tab
    sys.exit(1)

ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data

def eval_js(expr):
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner: return None
        return inner.get("result", {}).get("value")
    return None

send("Page.enable")
send("Runtime.enable")

# Step 1: Navigate to product list
print("\nStep 1: Navigating to product list...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/list/live/all"})
time.sleep(6)

url = eval_js("window.location.href")
print(f"URL after navigate: {url[:100] if url else 'ERROR'}")

if url and "login" in url.lower():
    print("REDIRECTED TO LOGIN!")
    sock.close()
    sys.exit(1)

# Step 2: Check product list
title = eval_js("document.title")
print(f"Title: {title}")

# Step 3: Navigate to specific product
print("\nStep 2: Navigating to product edit...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299/edit"})
time.sleep(6)

url2 = eval_js("window.location.href")
print(f"URL: {url2[:100] if url2 else 'ERROR'}")

if url2 and "login" in url2.lower():
    print("REDIRECTED TO LOGIN on product edit!")
    sock.close()
    sys.exit(1)

# Step 4: We're on the product page! Find Envio tab
print("\nStep 3: On product page! Looking for Envio...")

# All clickable elements
items = eval_js("Array.from(document.querySelectorAll('a, button, [role=tab], span, div[class*=tab], li')).map(e => ({tag: e.tagName, text: (e.textContent||'').trim().substring(0,30), cls: (e.className||'').substring(0,30)})).filter(x => x.text.toLowerCase().includes('envio') || x.text.toLowerCase().includes('envio')).slice(0,5)")
print(f"Envio elements: {items}")

# If we got here, also check logistics
logistics = eval_js("document.querySelectorAll('.logistics-item').length")
print(f"Logistics items count: {logistics}")

sock.close()
