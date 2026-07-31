"""Simple DOM exploration."""
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

# Count all elements
r = send("Runtime.evaluate", {"expression": "document.querySelectorAll('*').length", "returnByValue": True})
print(f"Total elements: {r['result']['value']}")

# Get body children tags
r = send("Runtime.evaluate", {"expression": "Array.from(document.body.children).map(c => c.tagName + '#' + c.id + '.' + (c.className||'')).join(' | ')", "returnByValue": True})
print(f"Body children: {r['result']['value']}")

# Check for any input elements page-wide
r = send("Runtime.evaluate", {"expression": "document.querySelectorAll('input[type=email], input[type=password], input[type=text]').length", "returnByValue": True})
print(f"Inputs found: {r['result']['value']}")

# Check all shadow roots
r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); for (const el of all) { if (el.shadowRoot) { return el.tagName + '#' + el.id + ' shadowChildren=' + el.shadowRoot.children.length; } } return 'none'; }()""", "returnByValue": True})
print(f"Shadow DOM: {r['result']['value']}")

# Check iframe content
r = send("Runtime.evaluate", {"expression": """() => { const iframe = document.querySelector('iframe'); if (!iframe) return 'no iframe'; try { const doc = iframe.contentDocument || iframe.contentWindow.document; return doc.body.innerHTML.substring(0,1000); } catch(e) { return 'iframe blocked: ' + e.message; } }()""", "returnByValue": True})
print(f"Iframe content: {r['result']['value']}")

sock.close()
