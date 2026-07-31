"""Try CDP login to refresh cookies."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = resp.json()
ws_url = tab.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data.get("result")

send("Page.enable")

# Navigate to login page
send("Page.navigate", {"url": "https://accounts.shopee.com.br/seller/login"})
time.sleep(8)

# Check URL
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Login page URL: {url}")

# Check if user is already logged in (redirected away from login)
if "login" not in url.lower():
    print("Ja esta logado! Redirecionado para:", url[:80])
    sock.close()
    req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
    sys.exit(0)

# Check body for login form
r = send("Runtime.evaluate", {"expression": "document.body.innerText.substring(0, 2000)", "returnByValue": True})
body = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Login page body:\n{body}")

# Check for email/password fields
r = send("Runtime.evaluate", {"expression": """() => { const inputs = document.querySelectorAll('input[type="email"], input[type="text"], input[type="password"]'); const info = []; for (const inp of inputs) { info.push({type: inp.type, name: inp.name, id: inp.id, placeholder: (inp.placeholder||''), cls: (inp.className||'').substring(0,30)}); } return JSON.stringify(info); }()""", "returnByValue": True})
inputs = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Input fields: {inputs}")

# Check for buttons
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('button, [type="submit"]'); const info = []; for (const b of btns) { info.push({text: b.textContent.trim().substring(0,30), cls: (b.className||'').substring(0,40)}); } return JSON.stringify(info); }()""", "returnByValue": True})
btns = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Buttons: {btns}")

# Check if Google SSO is available
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); for (const el of all) { if (el.textContent.includes('Google') || el.textContent.includes('google')) { return el.textContent.trim().substring(0,100) + ' | ' + el.tagName + ' ' + (el.className||'').substring(0,40); } } return 'no google'; }()""", "returnByValue": True})
google = ((r.get("result") or {}).get("value", "") if r else "")
print(f"Google SSO: {google}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
