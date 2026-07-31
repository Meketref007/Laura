"""Test proper toggle + Aplicar button flow."""
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

def js(expr, await_promise=True):
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner:
            print(f"  JS Error: {inner['exceptionDetails'].get('text','')}")
            return None
        return inner.get("result", {}).get("value")
    return None

PRODUCT_ID = "58256032299"
send("Page.enable")
send("Runtime.enable")

# Navigate to product
print("Navigating...")
send("Page.navigate", {"url": f"https://seller.shopee.com.br/portal/product/{PRODUCT_ID}"})
time.sleep(7)

# Click Envio
print("Clicking Envio...")
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

# Initial state
initial = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"Initial: {initial}")

# Use MouseEvent dispatch instead of element.click()
toggle_result = js("""(function() {
  var switches = document.querySelectorAll('.eds-switch');
  if (!switches || switches.length === 0) return 'no switches';
  var s = switches[0];
  s.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
  return 'clicked';
})()""")
print(f"Toggle result: {toggle_result}")
time.sleep(2)

# Check state after toggle
after_toggle = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After toggle: {after_toggle}")

# Find available buttons
btns = js("""(function() {
  var b = document.querySelectorAll('button');
  var r = [];
  for (var i = 0; i < b.length; i++) {
    var txt = b[i].textContent.trim().substring(0,40);
    var d = b[i].disabled;
    var v = b[i].offsetParent !== null;
    r.push({text: txt, disabled: d, visible: v});
  }
  return JSON.stringify(r);
})()""")
print(f"All buttons:\n{btns}")

# Try clicking "Aplicar" via MouseEvent
print("\nClicking Aplicar...")
aplicar = js("""(function() {
  var btns = document.querySelectorAll('button');
  for (var i = 0; i < btns.length; i++) {
    var txt = btns[i].textContent.trim().toLowerCase();
    if (txt.indexOf('aplicar') >= 0 && !btns[i].disabled && btns[i].offsetParent !== null) {
      btns[i].dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      return btns[i].textContent.trim();
    }
  }
  return '';
})()""")
print(f"Aplicar clicked: {aplicar}")

time.sleep(5)

# Check state after save
after_save = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After save: {after_save}")

# Look for success indicator
success = js("""(function() {
  var all = document.querySelectorAll('*');
  for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (!e.offsetParent) continue;
    var t = e.textContent.trim().toLowerCase();
    if ((t.indexOf('sucesso') >= 0 || t.indexOf('salvo') >= 0) && t.length < 100) {
      return e.tagName + ' ' + (e.className||'').substring(0,30) + ' ' + t.substring(0,80);
    }
  }
  return 'none visible';
})()""")
print(f"Success: {success}")

# Reload and verify
print("\nReloading...")
send("Page.reload")
time.sleep(8)

js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

final = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After reload: {final}")

sock.close()
