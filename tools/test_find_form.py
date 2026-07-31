"""Find the actual login form container."""
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
        if data.get("id") == mid: return data

# Check inputs
r = send("Runtime.evaluate", {"expression": "document.querySelectorAll('input').length", "returnByValue": True})
print("inputs:", r["result"]["value"])

# Check nwsisqoyuh div
r = send("Runtime.evaluate", {"expression": "document.getElementById('nwsisqoyuh')?.textContent?.substring(0,500) || 'not found'", "returnByValue": True})
print("nwsiq:", r["result"]["value"][:100])

# Check all visible text
r = send("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
print("body text:", r["result"]["value"][:500])

sock.close()
