"""Test global toggle using existing tab with valid session."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

# Find an existing seller tab - DON'T create new one
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    url = t.get("url", "")
    if "seller.shopee.com.br" in url and "login" not in url and url != "https://seller.shopee.com.br/404":
        target = t
        print(f"Using tab: {t.get('id','')[:20]} | {url[:80]}")
        break
if not target:
    print("No valid seller tab found")
    sys.exit(1)

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
                if "exceptionDetails" in inner:
                    return None
                return inner.get("result", {}).get("value")
            return None

send("Page.enable")
send("Runtime.enable")

# Navigate to global settings page
print("Navigating to global shipping settings...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(8)

url = js("window.location.href")
print(f"URL: {url[:80] if url else '?'}")

if url and "login" in url:
    print("REDIRECTED TO LOGIN")
    sock.close()
    sys.exit(1)

# Get initial state
state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"Initial state: {state}")

# Show channel names
names = js("""JSON.stringify(Array.from(document.querySelectorAll('.channel-setting-header')).map(function(h){return h.textContent.trim()}))""")
print(f"Channels: {names}")

# Find and click the switch for "Retirada pelo Comprador"
channel_name = "retirada"
toggle_js = ("(function() {" +
  "var switches = document.querySelectorAll('.eds-switch');" +
  "for (var i = 0; i < switches.length; i++) {" +
    "var header = switches[i].closest('.channel-setting-header');" +
    "if (!header) continue;" +
    "var text = header.textContent.trim().toLowerCase();" +
    "if (text.indexOf('" + channel_name + "') >= 0) {" +
      "var open = switches[i].classList.contains('eds-switch--open');" +
      "switches[i].click();" +
      "return JSON.stringify({clicked: true, wasOpen: open, name: header.textContent.trim()});" +
    "}" +
  "}" +
  "return JSON.stringify({clicked: false});" +
"})()")
toggle_r = js(toggle_js)
print(f"Toggle result: {toggle_r}")

time.sleep(3)

# Check state after toggle
state2 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"State after toggle: {state2}")

# Click Confirmar
confirm = js("""(function() {
  var btns = document.querySelectorAll('button');
  for (var i = 0; i < btns.length; i++) {
    var t = btns[i].textContent.trim().toLowerCase();
    if ((t === 'confirmar' || t === 'confirm') && btns[i].offsetParent !== null) {
      btns[i].click();
      return 'clicked';
    }
  }
  return 'not found';
})()""")
print(f"Confirm result: {confirm}")
time.sleep(4)

state3 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"State after confirm: {state3}")

# Reload
print("\nReloading...")
send("Page.reload")
time.sleep(8)

state4 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After reload: {state4}")

sock.close()
