"""Explore shipping config pages in Seller Center."""
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
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner: return None
        return inner.get("result", {}).get("value")
    return None

send("Page.enable")
send("Runtime.enable")

# Navigate to home
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(5)

# Find all sidebar links
links = js("""JSON.stringify(Array.from(document.querySelectorAll('a[href*=\"/portal/\"]')).map(function(a) {
  return {href: a.href.substring(0, 80), text: (a.textContent || '').trim().substring(0, 40)};
}))""")
print("Sidebar links:")
if links:
    for l in json.loads(links):
        if any(x in l["text"].lower() for x in ["envio", "shipping", "logistic", "config"]):
            print(f"  ** {l['text']}: {l['href']}")
    print(f"\nTotal links: {len(json.loads(links))}")

# Navigate to shipping settings page directly
print("\n--- Navigating to shipping settings pages ---")
for path in ["/portal/shipping/config", "/portal/shipping", "/portal/shipping/list", "/portal/product/shipping/config"]:
    url = f"https://seller.shopee.com.br{path}"
    send("Page.navigate", {"url": url})
    time.sleep(4)
    curr = js("window.location.href")
    title = js("document.title")
    body_preview = js("document.body.innerText.substring(0, 300)")
    if curr:
        print(f"\n{path}:")
        print(f"  URL: {curr[:80]}")
        print(f"  Title: {title}")
        if body_preview:
            print(f"  Body: {body_preview[:200]}")

sock.close()
