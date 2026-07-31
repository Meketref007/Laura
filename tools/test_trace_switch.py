"""Find correct click target and trace parent chain."""
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

# Navigate to product
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)

# Click Envio
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Trace parent chain from eds-switch up to logistics-item
chain = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return 'no switches';
  function trace(el) {
    var chain = [];
    var cur = el;
    var depth = 0;
    while (cur && depth < 10) {
      chain.push({
        tag: cur.tagName,
        cls: (cur.className || '').substring(0, 40),
        id: cur.id,
        visible: cur.offsetParent !== null,
        text: (cur.textContent || '').trim().substring(0, 30)
      });
      cur = cur.parentElement;
      depth++;
    }
    return chain;
  }
  return JSON.stringify(trace(s[0]));
})()""")
print(f"Switch[0] parent chain:\n{json.dumps(json.loads(chain) if chain else [], indent=2)}")

# Check what happens when clicking the switch's parent or grandparent
click_targets = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return 'no switches';
  // Try to click the invisible inner elements
  var inner = s[0].querySelector('input, [type=checkbox], [type=radio], span');
  return inner ? inner.tagName + ' ' + (inner.className || '') : 'no inner input';
})()""")
print(f"\nInner elements: {click_targets}")

# Get ALL eds-switch HTML including parents
html = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return 'no switches';
  return Array.from(s).map(function(sw, idx) {
    var p = sw.parentElement;
    var gp = p ? p.parentElement : null;
    return {
      idx: idx,
      switchHTML: sw.outerHTML.substring(0, 200),
      parentHTML: p ? p.outerHTML.substring(0, 200) : '',
      gpHTML: gp ? gp.outerHTML.substring(0, 200) : ''
    };
  });
})()""")
print(f"\nRaw HTML:\n{html}")

sock.close()
