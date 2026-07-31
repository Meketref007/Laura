"""Get parent chain of eds-switch elements."""
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
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Parent chain from switch[0]
js_code = """
(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return '[]';
  var chain = [];
  var cur = s[0];
  for (var i = 0; i < 8; i++) {
    if (!cur) break;
    chain.push({
      tag: cur.tagName,
      cls: (cur.className || '').substring(0, 40),
      visible: cur.offsetParent !== null,
      text: (cur.textContent || '').trim().substring(0, 30)
    });
    cur = cur.parentElement;
  }
  return JSON.stringify(chain);
})()
"""
chain = js(js_code)
print("Switch[0] chain:", chain)

# Second switch
js_code2 = """
(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length < 2) return '[]';
  var chain = [];
  var cur = s[1];
  for (var i = 0; i < 8; i++) {
    if (!cur) break;
    chain.push({
      tag: cur.tagName,
      cls: (cur.className || '').substring(0, 40),
      visible: cur.offsetParent !== null,
      text: (cur.textContent || '').trim().substring(0, 30)
    });
    cur = cur.parentElement;
  }
  return JSON.stringify(chain);
})()
"""
chain2 = js(js_code2)
print("Switch[1] chain:", chain2)

# Check if the switches are inside logistics-item
js_code3 = """
(function() {
  var s = document.querySelectorAll('.eds-switch');
  var r = [];
  for (var i = 0; i < s.length; i++) {
    var inside = s[i].closest('.logistics-item');
    r.push({idx: i, insideLogistics: inside ? 'YES text=' + inside.textContent.trim().substring(0,40) : 'NO', open: s[i].classList.contains('eds-switch--open')});
  }
  return JSON.stringify(r);
})()
"""
loc = js(js_code3)
print("Switch location:", loc)

# Get switch in context of its parent popover
js_code4 = """
(function() {
  var all = document.querySelectorAll('.popover-wrap.field-disabled-tips');
  var r = [];
  for (var i = 0; i < all.length; i++) {
    var sw = all[i].querySelector('.eds-switch');
    if (sw) {
      var btn = all[i].querySelector('button');
      r.push({
        idx: i,
        hasSwitch: true,
        open: sw.classList.contains('eds-switch--open'),
        hasBtn: btn ? btn.textContent.trim().substring(0,30) : 'NONE',
        btnVisible: btn ? btn.offsetParent !== null : false,
        allBtns: Array.from(all[i].querySelectorAll('button')).map(function(b){return{text:b.textContent.trim().substring(0,30),disabled:b.disabled,visible:b.offsetParent!==null}})
      });
    }
  }
  return JSON.stringify(r);
})()
"""
popover = js(js_code4)
print("Popover details:", popover)

# Now try clicking the switch's visible parent element
js_code5 = """
(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (s.length === 0) return 'no switches';
  // The switch is inside popover-wrap > inline-list-item
  // Click the toggle and watch the popover buttons
  s[0].click();
  return 'clicked';
})()
"""
click = js(js_code5)
print("Click result:", click)
time.sleep(3)

# Check if any new buttons became visible after click
js_code6 = """
(function() {
  var btns = document.querySelectorAll('.popover-wrap.field-disabled-tips button');
  return JSON.stringify(Array.from(btns).map(function(b) {
    return {text: b.textContent.trim().substring(0,30), disabled: b.disabled, visible: b.offsetParent !== null};
  }));
})()
"""
after = js(js_code6)
print("Buttons after click:", after)

sock.close()
