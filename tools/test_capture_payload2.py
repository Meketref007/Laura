"""Capture request payload of pre_check_logistic."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
all_reqs = []

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
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(8)

# Drain events
sock.settimeout(0.05)
try:
    while True:
        raw = sock.recv()
        data = json.loads(raw)
        method = data.get("method", "")
        if method == "Network.requestWillBeSent":
            r = data.get("params", {}).get("request", {})
            url = r.get("url", "")
            if "pre_check_logistic" in url:
                all_reqs.append({"url": url, "post": r.get("postData", "{}"), "method": r.get("method","")})
except:
    pass
sock.settimeout(None)

print("Pre-click requests cleared.")

# Click toggle
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(2)

# Collect the request
sock.settimeout(0.5)
try:
    while True:
        raw = sock.recv()
        data = json.loads(raw)
        method = data.get("method", "")
        if method == "Network.requestWillBeSent":
            r = data.get("params", {}).get("request", {})
            url = r.get("url", "")
            if "pre_check_logistic" in url:
                post_data = r.get("postData", "{}")
                print(f"\n=== Request ===")
                print(f"URL: {url[:150]}")
                print(f"Method: {r.get('method','')}")
                print(f"POST body:\n{post_data[:2000]}")
                all_reqs.append(post_data)
except:
    pass
sock.settimeout(None)

sock.close()
