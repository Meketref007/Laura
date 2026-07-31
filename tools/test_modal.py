"""Explore the modal content and find login form elements."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller/login" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data.get("result")

# Check #modal content
r = send("Runtime.evaluate", {"expression": "document.getElementById('modal')?.innerHTML?.substring(0, 3000) || 'NO MODAL'", "returnByValue": True})
print(f"#MODAL HTML:\n{r['result']['value']}")

# Check #main content
r = send("Runtime.evaluate", {"expression": "document.getElementById('main')?.innerHTML?.substring(0, 3000) || 'NO MAIN'", "returnByValue": True})
print(f"#MAIN HTML:\n{r['result']['value']}")

# Describe the 2 input fields found
r = send("Runtime.evaluate", {"expression": """() => { const inputs = document.querySelectorAll('input[type=email], input[type=password], input[type=text]'); return Array.from(inputs).map(i => ({type: i.type, name: i.name, id: i.id, placeholder: i.placeholder, cls: (i.className||'').substring(0,40), parent: (i.parentElement?.tagName||''), visible: i.offsetParent !== null})).join(' | '); }()""", "returnByValue": True})
print(f"INPUTS: {r['result']['value']}")

# Check all buttons
r = send("Runtime.evaluate", {"expression": """() => { const btns = document.querySelectorAll('button, [role=button], a[class*=btn]'); return Array.from(btns).map(b => ({text: (b.textContent||'').trim().substring(0,40), cls: (b.className||'').substring(0,40), visible: b.offsetParent !== null})).join(' | '); }()""", "returnByValue": True})
print(f"BUTTONS: {r['result']['value']}")

sock.close()
