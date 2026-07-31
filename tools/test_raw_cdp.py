"""Debug CDP raw responses."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), tabs[0])
print(f"Using tab: {target.get('url','')[:80]}")

ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})

# Send Runtime.enable and read ALL responses
sock.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
time.sleep(1)
sock.settimeout(1)
responses = []
while True:
    try:
        raw = sock.recv()
        data = json.loads(raw)
        responses.append(data)
        d_id = data.get("id")
        method = data.get("method", "")
        print(f"  [id={d_id}, method={method[:30]}]: {json.dumps(data, indent=2)[:200]}")
    except ws.WebSocketTimeoutException:
        break
    except Exception as e:
        print(f"  Error: {e}")
        break

# Now try eval
sock.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": "document.title", "returnByValue": True}}))
time.sleep(1)
while True:
    try:
        raw = sock.recv()
        data = json.loads(raw)
        print(f"  [id={data.get('id')}]: {json.dumps(data, indent=2)[:300]}")
    except ws.WebSocketTimeoutException:
        break

sock.close()
