"""Simplified global toggle test."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

# Open a new tab for this test
resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
target = resp.json()
print(f"New tab: {target.get('id','')[:20]}")

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

# Navigate to shipping channel settings
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(8)

url = js("window.location.href")
print(f"URL: {url[:80] if url else '?'}")

# Check state
state = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"State: {state}")

# Check save buttons
btns = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b){var t=b.textContent.trim().toLowerCase();return t.indexOf('salvar')>=0||t.indexOf('aplicar')>=0;}).map(function(b){return{text:b.textContent.trim(),disabled:b.disabled,visible:b.offsetParent!==null}}))""")
print(f"Save buttons: {btns}")

# Click first toggle
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(3)

state2 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After toggle: {state2}")

btns2 = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b){var t=b.textContent.trim().toLowerCase();return t.indexOf('salvar')>=0||t.indexOf('aplicar')>=0;}).map(function(b){return{text:b.textContent.trim(),disabled:b.disabled,visible:b.offsetParent!==null}}))""")
print(f"Save buttons after: {btns2}")

# Reload
send("Page.reload")
time.sleep(8)

state3 = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After reload: {state3}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{target.get('id','')}", timeout=5)
