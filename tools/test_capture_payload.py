"""Capture response body of pre_check_logistic to understand save flow."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
req_id = None
resp_body = None
req_urls = []

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

# Start collecting
collected_reqs = []
sock.settimeout(0.1)
def drain():
    while True:
        try:
            raw = sock.recv()
            data = json.loads(raw)
            method = data.get("method", "")
            p = data.get("params", {})
            if method == "Network.requestWillBeSent":
                r = p.get("request", {})
                url = r.get("url", "")
                if "pre_check_logistic" in url:
                    rid = p.get("requestId", "?")
                    collected_reqs.append({"type": "req", "reqId": rid, "url": url[:120]})
            elif method == "Network.responseReceived":
                url = p.get("response", {}).get("url", "")
                rid = p.get("requestId", "?")
                if "pre_check_logistic" in url:
                    collected_reqs.append({"type": "resp", "reqId": rid, "url": url[:120], "reqId": rid})
        except ws.WebSocketTimeoutException:
            break
        except:
            break

send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)
drain()
collected_reqs.clear()

# Toggle + Aplicar
print("Clicking toggle[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(2)

# Wait a bit and drain events
time.sleep(1)
drain()

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
time.sleep(3)
drain()

print(f"\nCollected {len(collected_reqs)} events")
for evt in collected_reqs:
    print(f"  {evt['type']}: reqId={evt.get('reqId','?')} url={evt.get('url','?')[:80]}")

# Get response body for the last requestId
if collected_reqs:
    last_resp = next((e for e in reversed(collected_reqs) if e["type"] == "resp"), None)
    if last_resp:
        rid = last_resp["reqId"]
        print(f"\nFetching response body for requestId={rid}")
        try:
            body_resp = send("Network.getResponseBody", {"requestId": rid})
            if body_resp:
                body = body_resp.get("result", {}).get("body", "") if isinstance(body_resp, dict) else ""
                print(f"Body ({len(body)} bytes):\n{body[:2000]}")
        except Exception as e:
            print(f"Error getting body: {e}")

# Also try to get the request POST data
# Network.requestWillBeSent includes postData in params.request
print("\nAlso checking request details:")
for evt in collected_reqs:
    if evt["type"] == "req":
        print(f"  reqId={evt.get('reqId','?')}: {evt.get('url','?')[:80]}")

sock.close()
