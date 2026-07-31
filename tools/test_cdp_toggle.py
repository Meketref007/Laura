"""Test CDP toggle - now trying to click the Envio tab first."""
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
msg_id = 0

def send(method, params=None):
    global msg_id
    msg_id += 1
    sock.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = sock.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data.get("result")

send("Page.enable")

# Navigate to home first (SPA init)
print("1. Navegando para home...")
send("Page.navigate", {"url": "https://seller.shopee.com.br/"})
time.sleep(5)

# Navigate to product page
item_id = 58256032299
channel = "Retirada pelo Comprador"
enable = True
print(f"2. Navegando para produto {item_id}...")
send("Page.navigate", {"url": f"https://seller.shopee.com.br/portal/product/{item_id}"})
time.sleep(8)

cur = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
print(f"   URL atual: {((cur.get('result') or {}).get('value', '') if cur else '?')}")

# Step 3: Click on "Envio" tab
print("3. Clicando na aba Envio...")
click_envio = """() => {
  const allEls = document.querySelectorAll('a, button, div, span, li');
  for (const el of allEls) {
    if (el.textContent.trim().toLowerCase() === 'envio') {
      el.click();
      return 'clicou em: ' + el.tagName + ' ' + (el.className || '') + ' ' + el.textContent.trim();
    }
  }
  return 'nao encontrou Envio';
}"""
result = send("Runtime.evaluate", {"expression": f"({click_envio})()", "returnByValue": True})
val = ((result.get("result") or {}).get("value", "") if result else "")
print(f"   Result: {val}")
time.sleep(3)

# Step 4: Look for logistics-item after clicking Envio
print("4. Buscando logistics-item apos clicar em Envio...")
check_items = """() => {
  const items = document.querySelectorAll('.logistics-item');
  const info = [];
  for (const item of items) {
    const text = item.textContent.trim();
    const toggle = item.querySelector('.eds-switch');
    const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false;
    info.push({text: text.substring(0, 60), hasToggle: !!toggle, isOpen: isOpen});
  }
  return JSON.stringify(info);
}"""
result = send("Runtime.evaluate", {"expression": f"({check_items})()", "returnByValue": True})
val = ((result.get("result") or {}).get("value", "[]") if result else "[]")
print(f"   Items: {val}")

if '"text":"retirada pelo comprador"' in val.lower() or '"text":"Retirada pelo Comprador"' in val:
    print("\n5. OK, encontrado! Agora executando toggle...")
    js = """(args) => {
  const channel = args.channel.toLowerCase();
  const enable = args.enable;
  const items = document.querySelectorAll('.logistics-item');
  for (const item of items) {
    const text = item.textContent.toLowerCase();
    if (text.includes(channel) || text.includes('frete') || text.includes('envio')) {
      const toggle = item.querySelector('.eds-switch');
      if (!toggle) continue;
      const isOpen = toggle.classList.contains('eds-switch--open');
      if (isOpen !== enable) {
        toggle.click();
        return JSON.stringify({found: true, clicked: true, text: text.substring(0,60)});
      }
      return JSON.stringify({found: true, clicked: false, reason: 'ja no estado desejado'});
    }
  }
  return JSON.stringify({found: false});
}"""
    result = send("Runtime.evaluate", {
        "expression": f"({js})({json.dumps({'channel': channel, 'enable': enable})})",
        "returnByValue": True,
    })
    val = ((result.get("result") or {}).get("value", "{}") if result else "{}")
    print(f"   Toggle result: {val}")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab.get('id', '')}", timeout=5)
