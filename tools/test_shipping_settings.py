"""Explore shipping settings page."""
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

# Navigate to shipping settings
print("Navigating to shipping settings...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping"})
time.sleep(7)

url = js("window.location.href")
title = js("document.title")
print(f"URL: {url}")
print(f"Title: {title}")

body = js("document.body.innerText.substring(0, 3000)")
print(f"Body:\n{body}")

# Check for switches or toggles
switches = js("document.querySelectorAll('.eds-switch').length")
print(f"\nSwitches: {switches}")

# Check for buttons
btns = js("""JSON.stringify(Array.from(document.querySelectorAll('button')).filter(function(b){return b.offsetParent!==null}).map(function(b){return{text:b.textContent.trim().substring(0,30),disabled:b.disabled}}).slice(0,20))""")
print(f"Buttons:\n{btns}")

sock.close()
