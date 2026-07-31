"""Test if save happens on tab switch."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

def send(m, p=None):
    global mid; mid = globals().get("mid", 0) + 1; globals()["mid"] = mid
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

# Simplified: no global mid, use local counter
mid = 0
def sm(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data

# Override send
send = sm

send("Page.enable")
send("Runtime.enable")
send("Network.enable")

send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)

# Click Envio
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Drain
def drain():
    sock.settimeout(0.05)
    while True:
        try:
            raw = sock.recv()
        except:
            break
    sock.settimeout(None)
drain()

network = []
sock.settimeout(0.1)

def monitor(secs):
    end = time.time() + secs
    while time.time() < end:
        try:
            raw = sock.recv()
            data = json.loads(raw)
            m = data.get("method", "")
            if m in ("Network.requestWillBeSent", "Network.responseReceived"):
                p = data.get("params", {})
                if m == "Network.requestWillBeSent":
                    r = p.get("request", {})
                    url = r.get("url", "")
                    if "seller.shopee.com.br" in url and "api/" in url:
                        network.append({"t": time.time(), "m": "REQ", "url": url[:100], "method": r.get("method",""), "post": (r.get("postData","")[:500] if r.get("postData") else "")})
                else:
                    url = p.get("response", {}).get("url", "")
                    status = p.get("response", {}).get("status", 0)
                    if "seller.shopee.com.br" in url and "api/" in url:
                        network.append({"t": time.time(), "m": "RSP", "url": url[:100], "status": status})
        except:
            pass
    sock.settimeout(None)

print("Initial state:")
state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"  {state}")

# Toggle
print("\nToggling switch[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(3)
monitor(2)

# Click Aplicar
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
monitor(3)

# Switch to "Informação básica" tab (simulates user switching sections)
print("\nClicking 'Informação básica' tab...")
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase().indexOf('informação básica') >= 0) { e.click(); return true; } } return false; })()""")
time.sleep(5)
monitor(5)

print(f"\n=== Network ({len(network)} events) ===")
for e in network:
    if e["m"] == "REQ":
        print(f"  REQ {e['method']} {e['url']}")
        if e["post"]:
            print(f"    body: {e['post'][:300]}")
    else:
        print(f"  RSP {e['status']} {e['url']}")

# Now reload and check
print("\nReloading...")
send("Page.reload")
time.sleep(7)
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

final = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"Final state: {final}")

sock.close()
