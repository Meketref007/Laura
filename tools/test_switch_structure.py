"""Investigate exact DOM structure of the toggle elements."""
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

# Navigate
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)

# Click Envio and wait for logistics
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
for i in range(12):
    time.sleep(1)
    cnt = js("document.querySelectorAll('.logistics-item').length")
    if cnt and int(cnt) > 0:
        print(f"Logistics loaded after {i+1}s")
        break

# Get DETAILED structure of the first logistics-item
structure = js("""(function() {
  var items = document.querySelectorAll('.logistics-item');
  if (!items || items.length === 0) return 'no items';
  var item = items[0];
  function describe(el, depth) {
    if (!el || depth > 3) return '';
    var info = [];
    var tag = el.tagName.toLowerCase();
    var cls = (el.className || '').substring(0, 30);
    var txt = (el.textContent || '').trim().substring(0, 30);
    var vis = el.offsetParent !== null;
    var children = [];
    for (var i = 0; i < el.children.length; i++) {
      var c = describe(el.children[i], depth + 1);
      if (c) children.push(c);
    }
    return {tag: tag, cls: cls, text: txt, visible: vis, children: children};
  }
  return JSON.stringify(describe(item, 0));
})()""")
print(f"\nLogistics item structure:\n{structure[:2000]}")

# Also get the eds-switch structure
switch_html = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return 'no switches';
  return JSON.stringify(Array.from(s).map(function(sw, idx) {
    var parent = sw.parentElement;
    return {
      idx: idx,
      tag: sw.tagName,
      cls: sw.className,
      parentTag: parent ? parent.tagName : '',
      parentCls: parent ? (parent.className || '').substring(0,40) : '',
      innerHTML: sw.innerHTML.substring(0, 200),
      rect: JSON.stringify(sw.getBoundingClientRect())
    };
  }));
})()""")
print(f"\nSwitch details:\n{switch_html}")

sock.close()
