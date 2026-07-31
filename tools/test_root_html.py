"""Explore login page structure more deeply."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "")

import requests as req
import websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller/login" in t.get("url","")), None)

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

send("Page.enable")
send("Runtime.enable")
time.sleep(1)

# Check root element
r = send("Runtime.evaluate", {"expression": "document.getElementById('root') ? document.getElementById('root').innerHTML.substring(0, 5000) : 'NO ROOT'", "returnByValue": True})
root_html = ((r.get("result") or {}).get("value", "") if r else "")
print(f"#root HTML:\n{root_html}")

# List all scripts on page
r = send("Runtime.evaluate", {"expression": """() => { const s = document.querySelectorAll('script'); return Array.from(s).map(x => ({src: (x.src||'').substring(0,80), text: (x.textContent||'').trim().substring(0,100)})); }()""", "returnByValue": True})
scripts = ((r.get("result") or {}).get("value", []) if r else [])
for s in scripts:
    print(f"Script: src={s.get('src','')} | text={s.get('text','')}")

sock.close()
