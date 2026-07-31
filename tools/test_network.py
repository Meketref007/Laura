"""Intercept XHR to check if toggle auto-saves."""
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

# Now set up network monitoring - we need to handle events
# Try the handle-style approach: collect requests
sock.settimeout(0.05)
# Drain old events
try:
    while True:
        raw = sock.recv()
except:
    pass
sock.settimeout(3)

# Click the toggle
print("Clicking toggle[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(0.5)

# Collect network events for 5 seconds
print("Monitoring network...")
requests_seen = []
deadline = time.time() + 5
while time.time() < deadline:
    try:
        raw = sock.recv()
        data = json.loads(raw)
        method = data.get("method", "")
        if method == "Network.requestWillBeSent":
            p = data.get("params", {})
            req_data = p.get("request", {})
            url = req_data.get("url", "")
            method_r = req_data.get("method", "")
            # Filter relevant requests
            if any(x in url for x in ["api", "product", "logistics", "shipping", "channel"]):
                if "shopee" in url and method_r != "OPTIONS":
                    info = f"{method_r} {url[:120]}"
                    print(f"  REQ: {info}")
                    requests_seen.append(info)
        elif method == "Network.responseReceived":
            p = data.get("params", {})
            resp_data = p.get("response", {})
            url = resp_data.get("url", "")
            status = resp_data.get("status", 0)
            if any(x in url for x in ["api", "product", "logistics", "shipping"]) and "shopee" in url:
                print(f"  RSP: {status} {url[:100]}")
    except ws.WebSocketTimeoutException:
        pass
    except Exception as e:
        pass

print(f"\nTotal relevant requests: {len(requests_seen)}")
if requests_seen:
    for r in requests_seen:
        print(f"  {r}")

# Check state after toggle
state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"\nState: {state}")

sock.close()
