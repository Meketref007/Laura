"""Full cycle: toggle + Aplicar + reload."""
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

def get_state():
    return js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")

send("Page.enable")
send("Runtime.enable")

# Navigate to product
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/product/58256032299"})
time.sleep(7)

# Click Envio
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

initial = get_state()
print(f"Initial: {initial}")

# Step 1: Click the toggle (switch[0])
print("\nStep 1: Clicking switch[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(2)

state1 = get_state()
print(f"After toggle click: {state1}")

# Step 2: Find and click Aplicar button for the same channel
print("\nStep 2: Clicking Aplicar button...")
aplicar_js = ("(function() {" +
  "var items = document.querySelectorAll('.logistics-item');" +
  "if (!items || items.length === 0) return 'no items';" +
  "var item = items[0];" +
  "var btns = item.querySelectorAll('button');" +
  "for (var i = 0; i < btns.length; i++) {" +
    "var txt = btns[i].textContent.trim().toLowerCase();" +
    "if (txt.indexOf('aplicar') >= 0) {" +
      "btns[i].click();" +
      "return 'clicked: ' + btns[i].textContent.trim();" +
    "}" +
  "}" +
  "return 'no aplicar btn';" +
"})()")
aplicar_r = js(aplicar_js)
print(f"Aplicar: {aplicar_r}")

# Wait for save
time.sleep(5)

state2 = get_state()
print(f"After save: {state2}")

# Step 3: Reload and verify
print("\nStep 3: Reloading...")
send("Page.reload")
time.sleep(7)

js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

final = get_state()
print(f"After reload: {final}")

if initial == final:
    print("*** CHANGE DID NOT PERSIST ***")
else:
    print("*** CHANGE PERSISTED! ***")

sock.close()
