"""Test correct product edit URL and investigate navigation."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "product/list" in t.get("url","")), None)
if not target:
    target = next((t for t in tabs if t.get("url","").rstrip("/") == "https://seller.shopee.com.br"), None)
if not target:
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

def eval_js(expr):
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner: return None
        return inner.get("result", {}).get("value")
    return None

send("Page.enable")
send("Runtime.enable")

# Check current URL
url = eval_js("window.location.href")
print(f"Current: {url[:100] if url else '?'}")

if not url:
    print("Can't reach page, trying navigation...")
    send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/list/live/all"})
    time.sleep(5)

# Navigate to product page WITHOUT /edit suffix
prod_url = "https://seller.shopee.com.br/portal/product/58256032299"
print(f"\nNavigating to: {prod_url}")
send("Page.navigate", {"url": prod_url})
time.sleep(6)

url2 = eval_js("window.location.href")
print(f"URL: {url2[:100] if url2 else '?'}")

title2 = eval_js("document.title")
print(f"Title: {title2}")

body2 = eval_js("document.body.innerText.substring(0, 500)")
print(f"Body: {body2}")

# Try clicking first product in list instead
print("\n--- Alternative: click first product in list ---")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/list/live/all"})
time.sleep(5)

# Find product links
links = eval_js("Array.from(document.querySelectorAll('a[href*=\"/portal/product/\"]')).map(a => a.href).slice(0,5)")
print(f"Product links: {links}")

sock.close()
