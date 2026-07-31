"""Test toggle on global shipping settings page."""
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

# Navigate to shipping channel settings
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(7)

# Get initial state
state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"Initial: {state}")

# Get switch layout
layout = js("""JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i) {
  var parent = s.parentElement;
  var gp = parent ? parent.parentElement : null;
  var text = gp ? (gp.textContent || '').trim().substring(0,80) : '';
  return {idx: i, open: s.classList.contains('eds-switch--open'), cls: s.className, parentText: text};
}))""")
print(f"Layout: {layout}")

# Find save button
btns = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b) {
  var txt = b.textContent.trim().toLowerCase();
  return txt.indexOf('salvar') >= 0 || txt.indexOf('aplicar') >= 0;
}).map(function(b) { return {text: b.textContent.trim(), disabled: b.disabled, visible: b.offsetParent !== null}; }))""")
print(f"Save buttons: {btns}")

# Collect network
sock.settimeout(0.05)
def drain():
    while True:
        try:
            raw = sock.recv()
            data = json.loads(raw)
            m = data.get("method", "")
            if m == "Network.requestWillBeSent":
                r = data.get("params", {}).get("request", {})
                url = r.get("url", "")
                if "seller.shopee.com.br/api/" in url:
                    print(f"  API: {r.get('method')} {url[:100]}")
        except:
            break
    sock.settimeout(None)
drain()

# Click toggle
print("\nToggling switch[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(4)

state2 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After toggle: {state2}")

# Save button?
btns2 = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b) {
  var txt = b.textContent.trim().toLowerCase();
  return txt.indexOf('salvar') >= 0 || txt.indexOf('aplicar') >= 0;
}).map(function(b) { return {text: b.textContent.trim(), disabled: b.disabled, visible: b.offsetParent !== null}; }))""")
print(f"Save buttons after: {btns2}")

# Network
drain()

# Reload and check persistence
print("\nReloading...")
send("Page.reload")
time.sleep(7)
state3 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After reload: {state3}")

sock.close()
