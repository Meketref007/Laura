"""Try realistic mouse events to trigger React popover."""
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

# Navigate and click Envio
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Get switch bounding rect for realistic click
rect = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return null;
  var r = s[0].getBoundingClientRect();
  return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width/2, cy: r.y + r.height/2});
})()""")
print(f"Switch rect: {rect}")

# 1. Try Input.dispatchMouseEvent (CDP's own mouse event)
rect_data = json.loads(rect)
cx, cy = rect_data["cx"], rect_data["cy"]

# Mouse move to position
send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy})
time.sleep(0.2)

# Mouse down
send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1})
time.sleep(0.1)

# Mouse up
send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1})
time.sleep(2)

# Check if Aplicar buttons became visible
APLICAR_QUERY = ('(function() {' +
  'var all = document.querySelectorAll("button");' +
  'var found = [];' +
  'for (var i = 0; i < all.length; i++) {' +
    'var txt = all[i].textContent.trim().toLowerCase();' +
    'if (txt.indexOf("aplicar") >= 0) {' +
      'found.push({text: all[i].textContent.trim().substring(0,30), disabled: all[i].disabled, visible: all[i].offsetParent !== null, parentCls: (all[i].parentElement ? all[i].parentElement.className : "").substring(0,40)});' +
    '}' +
  '}' +
  'return JSON.stringify(found);' +
'})()')
aplicar = js(APLICAR_QUERY)
print(f"Aplicar buttons after mouse click: {aplicar}")

# Check switch state after realistic click
sw_state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"Switch state: {sw_state}")

# 2. Now that we may have opened the popover, try clicking Aplicar
APLICAR_JS = ('(function() {' +
  'var all = document.querySelectorAll("button");' +
  'for (var i = 0; i < all.length; i++) {' +
    'var txt = all[i].textContent.trim().toLowerCase();' +
    'if (txt.indexOf("aplicar") >= 0) {' +
      'all[i].click();' +
      'return all[i].textContent.trim().substring(0,30);' +
    '}' +
  '}' +
  "return '';" +
'})()')
click_aplicar = js(APLICAR_JS)
print(f"Aplicar clicked: {click_aplicar}")

time.sleep(3)

# Check state after save
sw_after = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"State after save attempt: {sw_after}")

sock.close()
