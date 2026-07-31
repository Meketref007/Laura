"""Explore login page DOM structure."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller/login" in t.get("url","")), None)
if not target:
    print("No login tab, creating new")
    resp = req.put("http://127.0.0.1:9222/json/new/https://accounts.shopee.com.br/seller/login", timeout=10)
    target = resp.json()
    time.sleep(5)

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
time.sleep(2)

# Get all top-level children of body
r = send("Runtime.evaluate", {"expression": """() => { const body = document.body; const children = []; for (const c of body.children) { children.push({tag: c.tagName, id: c.id || '', class: (c.className||'').substring(0,30), visible: c.offsetParent !== null, html: c.innerHTML.substring(0,500)}); } return JSON.stringify(children); }()""", "returnByValue": True})
children = ((r.get("result") or {}).get("value", "[]") if r else "[]")
import json as j; parsed = j.loads(children)
for c in parsed:
    print(f"\n=== <{c['tag']}> id={c['id']} class={c['class']} visible={c['visible']} ===")
    print(c['html'])

sock.close()
