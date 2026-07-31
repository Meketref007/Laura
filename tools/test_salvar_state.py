"""Check Salvar button state after Aplicar click."""
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

send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Check all Salvar buttons
def check_salvar():
    return js("""(function() {
  var all = document.querySelectorAll('button');
  var found = [];
  for (var i = 0; i < all.length; i++) {
    var txt = all[i].textContent.trim().toLowerCase();
    if (txt.indexOf('salvar') >= 0) {
      found.push({text: all[i].textContent.trim(), disabled: all[i].disabled, visible: all[i].offsetParent !== null});
    }
  }
  return JSON.stringify(found);
})()""")

print("Initial Salvar buttons:", check_salvar())

# Click toggle[0]
print("\nClicking toggle[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(2)
print("After toggle:", check_salvar())

# Click Aplicar
print("\nClicking Aplicar...")
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
print("After Aplicar:", check_salvar())

# Also check for any Non-disabled Salvar globally
print("\nAll buttons (visible, enabled):")
all_visible = js("""(function() {
  var all = document.querySelectorAll('button');
  var found = [];
  for (var i = 0; i < all.length; i++) {
    if (all[i].offsetParent !== null && !all[i].disabled) {
      var t = all[i].textContent.trim();
      if (t.length > 0) found.push({text: t.substring(0,30), disabled: all[i].disabled});
    }
  }
  return JSON.stringify(found);
})()""")
print(all_visible)

sock.close()
