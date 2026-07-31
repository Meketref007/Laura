"""Monitor ALL network requests during toggle + save cycle."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
req_data = []

def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data

# Enable all
send("Page.enable")
send("Runtime.enable")
send("Network.enable")

# Set up network listener - we'll drain events periodically
def drain():
    sock.settimeout(0.05)
    while True:
        try:
            raw = sock.recv()
            data = json.loads(raw)
            method = data.get("method", "")
            if method == "Network.requestWillBeSent":
                p = data.get("params", {}).get("request", {})
                url = p.get("url", "")
                m = p.get("method", "")
                if "seller.shopee.com.br/api/" in url and m != "OPTIONS":
                    req_data.append({"t": time.time(), "evt": "req", "url": url[:120], "method": m})
            elif method == "Network.responseReceived":
                p = data.get("params", {}).get("response", {})
                url = p.get("url", "")
                status = p.get("status", 0)
                if "seller.shopee.com.br/api/" in url:
                    req_data.append({"t": time.time(), "evt": "rsp", "url": url[:120], "status": status})
        except ws.WebSocketTimeoutException:
            break
        except:
            break
    sock.settimeout(None)

def js(expr):
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner: return None
        return inner.get("result", {}).get("value")
    return None

# Navigate
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)
drain()  # clear initial requests
req_data.clear()

print("--- Clicking toggle[0] ---")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(3)
drain()

print("--- Clicking Aplicar ---")
aplicar_js = ("(function() {" +
  "var items = document.querySelectorAll('.logistics-item');" +
  "if (!items || items.length === 0) return 'no items';" +
  "var item = items[0];" +
  "var btns = item.querySelectorAll('button');" +
  "for (var i = 0; i < btns.length; i++) {" +
    "var txt = btns[i].textContent.trim().toLowerCase();" +
    "if (txt.indexOf('aplicar') >= 0) {" +
      "btns[i].click();" +
      "return 'clicked: ' + btns[i].textContent.trim();" +
    "}" +
  "}" +
  "return 'no aplicar btn';" +
"})()")
ap_r = js(aplicar_js)
print(f"Result: {ap_r}")
time.sleep(5)
drain()

print(f"\n=== Network requests ({len(req_data)}) ===")
for r in req_data:
    ts = r["t"]
    evt = r["evt"]
    if evt == "req":
        print(f"  REQ  {r['method']} {r['url']}")
    else:
        print(f"  RSP  {r['status']} {r['url']}")

# Also check state
state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"\nFinal state: {state}")

sock.close()
