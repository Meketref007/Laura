"""Intercept login page XHR to find correct API endpoint."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "accounts.shopee.com.br" in t.get("url","") and "login" in t.get("url","")), None)
if not target:
    # Open new tab to login page
    resp = req.put("http://127.0.0.1:9222/json/new/https://accounts.shopee.com.br/seller/login", timeout=10)
    target = resp.json()
    print("Opened new login tab")

ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0

def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data.get("result")

def recv(timeout=5):
    sock.settimeout(timeout)
    try: return json.loads(sock.recv())
    except: return None

send("Page.enable")
send("Runtime.enable")
send("Network.enable")

collected = []
def on_msg(msg):
    if msg.get("method") == "Network.requestWillBeSent":
        p = msg.get("params", {})
        r = p.get("request", {})
        url = r.get("url", "")
        method = r.get("method", "")
        if "shopee" in url.lower() or "accounts" in url.lower():
            info = {"url": url[:120], "method": method, "type": p.get("type","?")}
            collected.append(info)
            print(f"{method} {url[:100]}")

# Wait for login page to fully load
# First, check current state
time.sleep(2)

# Navigate to login page
send("Page.navigate", {"url": "https://accounts.shopee.com.br/seller/login"})
time.sleep(6)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "") if r else "")
print(f"\nCurrent URL: {url[:80]}")

if "login" not in url.lower():
    print("Já logado!")
    sock.close()
    sys.exit(0)

# Get full body HTML to see the form structure
r = send("Runtime.evaluate", {"expression": "document.getElementById('root')?.innerText?.substring(0,2000) || document.body.innerText.substring(0,2000)", "returnByValue": True})
body = ((r.get("result") or {}).get("value", "") if r else "")
print(f"\nLogin page root:\n{body}")

# Check for input fields (maybe iframe?)
r = send("Runtime.evaluate", {"expression": "document.querySelectorAll('iframe').length", "returnByValue": True})
ifr = ((r.get("result") or {}).get("value", 0) if r else 0)
print(f"Iframes: {ifr}")

for i in range(ifr):
    r = send("Runtime.evaluate", {"expression": f"document.querySelectorAll('iframe')[{i}].src", "returnByValue": True})
    src = ((r.get("result") or {}).get("value", "?") if r else "?")
    print(f"  iframe[{i}]: {src[:100]}")

# Check for shadow DOM usage
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); for (const el of all) { if (el.shadowRoot) { return 'Has shadow root: ' + el.tagName + ' ' + (el.id || ''); } } return 'No shadow root'; }()""", "returnByValue": True})
sd = ((r.get("result") or {}).get("value", "") if r else "")
print(f"\nShadow DOM: {sd}")

# Look at the actual HTML
r = send("Runtime.evaluate", {"expression": "document.body.innerHTML.substring(0,3000)", "returnByValue": True})
html = ((r.get("result") or {}).get("value", "") if r else "")
print(f"\nBody HTML:\n{html}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{target.get('id','')}", timeout=5)
