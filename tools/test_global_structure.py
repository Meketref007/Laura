"""Investigate global page switch structure."""
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

send("Page.enable")
send("Runtime.enable")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(8)

# Get the parent chain of switch[0]
chain = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return 'no switches';
  function trace(el) {
    var c = [];
    var cur = el;
    for (var i = 0; i < 8; i++) {
      if (!cur) break;
      c.push({tag: cur.tagName, cls: (cur.className||'').substring(0,40), id: cur.id, visible: cur.offsetParent !== null, text: (cur.textContent||'').trim().substring(0,30)});
      cur = cur.parentElement;
    }
    return c;
  }
  return JSON.stringify(trace(s[0]));
})()""")
print(f"Switch[0] chain:\n{json.dumps(json.loads(chain) if chain else [], indent=2)}")

# Get all visible interactive elements near switches
interactive = js("""JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(sw, idx) {
  var item = sw.closest('[class*=channel], [class*=logistics], [class*=item], [class*=setting], li, tr, div');
  var btns = item ? Array.from(item.querySelectorAll('button')).map(function(b){return{text:b.textContent.trim(),disabled:b.disabled,visible:b.offsetParent!==null}}) : [];
  var toggles = item ? Array.from(item.querySelectorAll('.eds-switch')).length : 0;
  return {idx: idx, itemCls: (item?item.className:'').substring(0,40), itemText: (item?item.textContent.trim().substring(0,80):''), buttons: btns, toggles: toggles};
}))""")
print(f"\nInteractive: {interactive}")

# Try clicking with mouse event instead
rect = js("""(function() {
  var s = document.querySelectorAll('.eds-switch');
  if (!s || s.length === 0) return null;
  var r = s[0].getBoundingClientRect();
  return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
})()""")
if rect:
    rect_d = json.loads(rect)
    print(f"\nClicking at ({rect_d['x']:.0f}, {rect_d['y']:.0f}) with CDP mouse...")
    send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": rect_d["x"], "y": rect_d["y"], "button": "left", "clickCount": 1})
    send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": rect_d["x"], "y": rect_d["y"], "button": "left", "clickCount": 1})
    time.sleep(2)

state2 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After mouse click: {state2}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{target.get('id','')}", timeout=5)
