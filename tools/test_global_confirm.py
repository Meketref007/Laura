"""Global toggle with confirmation."""
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
send("Network.enable")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(8)

initial = get_state()
print(f"Initial: {initial}")

# Find the switch that is currently OPEN, click it to CLOSE it
# We want to toggle channel off to test
target_idx = None
state = json.loads(initial) if initial else []
for i, s in enumerate(state):
    if s["open"]:
        target_idx = i
        break

if target_idx is not None:
    print(f"\nClicking switch[{target_idx}] (currently open -> close)...")
    js(f"document.querySelectorAll('.eds-switch')[{target_idx}].click()")
    time.sleep(2)
    print(f"State: {get_state()}")

    # Check for confirmation dialog buttons
    btns = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b) {
      var t = b.textContent.trim().toLowerCase();
      return t.indexOf('confirmar') >= 0 || t.indexOf('cancelar') >= 0 || t.indexOf('confirm') >= 0;
    }).map(function(b) { return {text: b.textContent.trim(), disabled: b.disabled, visible: b.offsetParent !== null}; }))""")
    print(f"Confirm/Cancel buttons: {btns}")

    # Click Confirmar
    confirm_click = js("""(function() {
      var btns = document.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var t = btns[i].textContent.trim().toLowerCase();
        if ((t.indexOf('confirmar') >= 0 || t.indexOf('confirm') >= 0) && btns[i].offsetParent !== null) {
          btns[i].click();
          return 'clicked: ' + btns[i].textContent.trim();
        }
      }
      return 'not found';
    })()""")
    print(f"Confirm result: {confirm_click}")
    time.sleep(5)

    # State after confirm
    state_after = get_state()
    print(f"After confirm: {state_after}")

    # Reload
    print("\nReloading...")
    send("Page.reload")
    time.sleep(8)
    final = get_state()
    print(f"After reload: {final}")

    if initial != final:
        print("*** CHANGE PERSISTED! ***")
    else:
        print("*** CHANGE DID NOT PERSIST ***")
else:
    print("No open switch found to toggle")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{target.get('id','')}", timeout=5)
