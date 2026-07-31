"""Test if save happens on page navigation."""
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
send("Network.enable")

# Navigate to product
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)

# Click Envio
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Collect ALL requests indiscriminately
all_reqs = []
sock.settimeout(0.05)
def drain_all():
    while True:
        try:
            raw = sock.recv()
            data = json.loads(raw)
            method = data.get("method", "")
            p = data.get("params", {})
            if method == "Network.requestWillBeSent":
                r = p.get("request", {})
                url = r.get("url", "")
                if "seller.shopee.com.br" in url:
                    all_reqs.append({"t": time.time(), "evt": "req", "url": url[:120], "method": r.get("method",""), "post": (r.get("postData") or "")[:200]})
        except:
            break
    sock.settimeout(None)

# Drain initial page loads
drain_all()
print(f"Initial requests: {len(all_reqs)}")
all_reqs.clear()

# Toggle
print("Toggling switch[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(3)
drain_all()
print(f"After toggle: {len(all_reqs)} new requests")

# Aplicar
print("Clicking Aplicar...")
js("""(function() {
  var items = document.querySelectorAll('.logistics-item');
  if (!items || items.length === 0) return;
  var btns = items[0].querySelectorAll('button');
  for (var i = 0; i < btns.length; i++) {
    var txt = btns[i].textContent.trim().toLowerCase();
    if (txt.indexOf('aplicar') >= 0) { btns[i].click(); return; }
  }
})()""")
time.sleep(5)
drain_all()
print(f"After Aplicar: {len(all_reqs)} new requests")

# Now navigate to list page (simulating leave)
print("Navigating away to trigger save...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/list/live/all"})
time.sleep(5)
drain_all()
print(f"After nav: {len(all_reqs)} new requests")

print(f"\n=== All requests ({len(all_reqs)}) ===")
for r in all_reqs:
    print(f"  [{r['evt']}] {r['method']} {r['url']}")
    if r.get("post"):
        print(f"    POST: {r['post'][:200]}")

sock.close()
