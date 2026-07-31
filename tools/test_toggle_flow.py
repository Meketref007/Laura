"""Investigate correct toggle and save flow step by step."""
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
            return None
        return inner.get("result", {}).get("value")
    return None

PRODUCT_ID = "58256032299"
send("Page.enable")
send("Runtime.enable")
send("Page.navigate", {"url": f"https://seller.shopee.com.br/portal/product/{PRODUCT_ID}"})

# Wait for page to fully load
for i in range(20):
    ready = js("document.readyState")
    if ready == "complete":
        break
    time.sleep(1)

# Click Envio and wait for logistics items
print("Clicking Envio and waiting for logistics...")
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")

for i in range(15):
    time.sleep(1)
    items = js("document.querySelectorAll('.logistics-item').length")
    switches = js("document.querySelectorAll('.eds-switch').length")
    print(f"  t={i+1}s: items={items} switches={switches}")
    if items and int(items) > 0:
        break

# Get logistics structure
log_items = js("""JSON.stringify(Array.from(document.querySelectorAll('.logistics-item')).map(function(item, idx) {
  var toggle = item.querySelector('.eds-switch');
  var isOpen = toggle ? toggle.classList.contains('eds-switch--open') : null;
  var btns = item.querySelectorAll('button');
  var btnInfo = Array.from(btns).map(function(b) { return {text: b.textContent.trim(), disabled: b.disabled, visible: b.offsetParent !== null}; });
  return {idx: idx, text: item.textContent.trim().substring(0,80), isOpen: isOpen, buttons: btnInfo};
}))""")
print(f"\nLogistics items:\n{log_items}")

# Click the toggle (the actual switch DIV, not via dispatchEvent)
print("\n--- Clicking switch[0] via element.click() ---")
click_r = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return 'no switches';
  try {
    s[0].click();
    return 'clicked via element.click()';
  } catch(e) {
    return 'error: ' + e.message;
  }
})()""")
print(f"Click result: {click_r}")
time.sleep(3)

# Check what changed
switches_after = js("""JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))""")
print(f"Switches after click: {switches_after}")

# Check for visible popover/modal buttons
visible_btns = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b) { return b.offsetParent !== null && b.textContent.trim().length > 0; }).map(function(b) { return {text: b.textContent.trim().substring(0,40), disabled: b.disabled}; }))""")
print(f"Visible buttons: {visible_btns}")

# Check for any visible 'Aplicar' buttons specifically
aplicar_btns = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b) { return b.offsetParent !== null; }).filter(function(b) { return b.textContent.trim().toLowerCase().indexOf('aplicar') >= 0; }).map(function(b){return{text:b.textContent.trim(),disabled:b.disabled}}))""")
print(f"Visible Aplicar buttons: {aplicar_btns}")

# Check for popovers
popovers = js("""JSON.stringify(Array.from(document.querySelectorAll('[class*=popover], [class*=popup], [class*=modal], [class*=dialog]')).filter(function(e){return e.offsetParent!==null}).map(function(e){return{class:(e.className||'').substring(0,40),text:e.textContent.trim().substring(0,80)}}))""")
print(f"Visible popovers: {popovers}")

sock.close()
