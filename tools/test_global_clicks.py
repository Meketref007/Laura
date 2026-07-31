"""Try clicking different targets in the global page."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
target = resp.json()
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

def send(m, p=None):
    global mid; mid = globals().get("mid", 0) + 1; globals()["mid"] = mid
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data

def js(expr):
    global mid; mid = globals().get("mid", 0) + 1; globals()["mid"] = mid
    sock.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid:
            if "result" in data:
                inner = data["result"]
                if "exceptionDetails" in inner: return None
                return inner.get("result", {}).get("value")
            return None

def get_state():
    return js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")

send("Page.enable")
send("Runtime.enable")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(8)

print("Initial:", get_state())

# Try clicking the channel-setting-enable-toggle div
print("\n1. Clicking channel-setting-enable-toggle...")
js("document.querySelector('.channel-setting-enable-toggle')?.click()")
time.sleep(3)
print("   State:", get_state())

# Try clicking the popover ref
print("\n2. Clicking eds-popover__ref...")
js("document.querySelector('.eds-popover__ref')?.click()")
time.sleep(3)
print("   State:", get_state())

# Try clicking the inner switch via CDP mouse click event with simulated React
print("\n3. Trying React-friendly click on switch...")
js("""(function() {
  var s = document.querySelector('.eds-switch');
  if (!s) return 'no switch';
  // Create and dispatch a native click event (not MouseEvent which React ignores)
  var evt = document.createEvent('MouseEvents');
  evt.initEvent('click', true, true);
  s.dispatchEvent(evt);
  return 'clicked via initEvent';
})()""")
time.sleep(3)
print("   State:", get_state())

# Try clicking the channel-setting-header title area
print("\n4. Clicking channel-setting-header text (to expand)...")
js("document.querySelector('.channel-setting-header')?.click()")
time.sleep(3)
print("   State:", get_state())

# Check if there are hidden elements revealed
body = js("document.body.innerText.substring(1000, 3000)")
print(f"\nBody section:\n{body}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{target.get('id','')}", timeout=5)
