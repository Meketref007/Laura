"""Debug CDP - just listen to events."""
import json, ssl, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import websocket as ws
import requests as req

r = req.put("http://127.0.0.1:9222/json/new", timeout=10)
tab = r.json()
ws_url = tab.get("webSocketDebuggerUrl", '')

ws_conn = ws.create_connection(ws_url, timeout=30,
    sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
ws_conn.settimeout(3)

# Send Page.enable
msg = json.dumps({"id": 1, "method": "Page.enable", "params": {}})
ws_conn.send(msg)
print("Sent Page.enable, reading responses...")

for i in range(5):
    try:
        raw = ws_conn.recv()
        data = json.loads(raw)
        if "id" in data:
            print(f"Response id={data['id']}: {json.dumps(data, ensure_ascii=False)[:200]}")
        else:
            print(f"Event {data.get('method','?')}: {json.dumps(data, ensure_ascii=False)[:200]}")
    except Exception as e:
        print(f"recv error: {e}")
        break

# Now navigate
msg2 = json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": "https://shopee.com.br/search?keyword=Xiaomi+Band+8"}})
ws_conn.send(msg2)
print("\nSent navigate, reading...")

for i in range(20):
    try:
        raw = ws_conn.recv()
        data = json.loads(raw)
        if "id" in data:
            if data["id"] == 2:
                print(f"Navigate response: {json.dumps(data, ensure_ascii=False)[:200]}")
            else:
                print(f"Unknown response id={data['id']}")
        else:
            method = data.get("method", "?")
            if "frame" in method.lower() or "load" in method.lower():
                print(f"Page event: {method}")
    except Exception as e:
        print(f"Timeout after {i} events")
        break

time.sleep(3)

# Evaluate
msg3 = json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {"expression": "document.title", "awaitPromise": False}})
ws_conn.send(msg3)
print("\nSent evaluate, reading...")

for i in range(10):
    try:
        raw = ws_conn.recv()
        data = json.loads(raw)
        if "id" in data:
            if data["id"] == 3:
                print(f"Evaluate response: {json.dumps(data, ensure_ascii=False)[:300]}")
                break
            else:
                print(f"Unknown response id={data['id']}")
        else:
            method = data.get("method", "?")
            if i < 3:
                print(f"Event: {method}")
    except Exception as e:
        print(f"Timeout on evaluate")
        break

ws_conn.close()
