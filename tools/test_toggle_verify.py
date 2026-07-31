"""Test toggle + verify persistence."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import requests as req
import websocket as ws

SELLER_BASE = "https://seller.shopee.com.br"

# --- Find existing seller tab or create one ---
tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = None
for t in tabs:
    u = t.get("url", "")
    if "seller.shopee.com.br" in u and "product" in u:
        target = t; break
if not target:
    for t in tabs:
        if "seller.shopee.com.br" in t.get("url", ""):
            target = t; break
if not target:
    resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
    target = resp.json()

ws_url = target.get("webSocketDebuggerUrl", "")
print(f"Usando aba: {target.get('id','')[:30]} | URL: {target.get('url','')[:80]}")

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

# Inject cookies from JSON for safety
try:
    from shopee_agent.seller_center import load_cookies
    cs = load_cookies()
    if cs:
        for c in cs.cookies:
            if c.is_expired(): continue
            p2 = {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": c.secure, "httpOnly": c.httpOnly}
            if c.expirationDate: p2["expires"] = c.expirationDate
            send("Network.setCookie", p2)
        print(f"Injetados {sum(1 for c in cs.cookies if not c.is_expired())} cookies via CDP")
except Exception as e:
    print(f"Cookie inject warning: {e}")

# Navigate to home (SPA init)
send("Page.navigate", {"url": f"{SELLER_BASE}/"})
time.sleep(6)

# Check for login redirect
r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "") if r else "")
if "login" in url:
    print("REDIRECTED TO LOGIN - auth expired!")
    sock.close()
    sys.exit(1)
print(f"Home loaded: {url[:60]}")

# Navigate to product
ITEM_ID = 58256032299
send("Page.navigate", {"url": f"{SELLER_BASE}/portal/product/{ITEM_ID}"})
time.sleep(8)

r = send("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
url = ((r.get("result") or {}).get("value", "") if r else "")
if "login" in url:
    print("REDIRECTED TO LOGIN on product page!")
    sock.close()
    sys.exit(1)
print(f"Product page loaded: {url[:80]}")

# Click Envio tab
r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a, button, div, span, li'); for (const e of els) { const t = e.textContent.trim().toLowerCase(); if (t === 'envio' || t === 'envio ') { e.click(); return e.tagName + ' ' + e.textContent.trim(); } } return 'NOT FOUND'; })()""", "returnByValue": True})
tab_click = ((r.get("result") or {}).get("value", "?") if r else "?")
print(f"Envio click: {tab_click}")
time.sleep(4)

# Check logistics
r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); const info = []; for (const item of items) { const text = item.textContent.trim(); const toggle = item.querySelector('.eds-switch'); const isOpen = toggle ? toggle.classList.contains('eds-switch--open') : false; info.push({text: text.substring(0,60), isOpen: isOpen}); } return JSON.stringify(info); }()""", "returnByValue": True})
val = ((r.get("result") or {}).get("value", "[]") if r else "[]")
print(f"Logistics BEFORE: {val}")

if val == "[]" or val == "[]":
    print("NO LOGISTICS ITEMS FOUND - page content not loaded")
    sock.close()
    sys.exit(1)

items = json.loads(val)
target_item = None
for item in items:
    if "retirada" in item.get("text", "").lower():
        target_item = item
        break

if not target_item:
    print("Retirada pelo Comprador not found in logistics items")
    sock.close()
    sys.exit(1)

print(f"\nRetirada pelo Comprador encontrado! isOpen={target_item['isOpen']}")

if target_item["isOpen"]:
    print("JA ESTA ATIVADO - nao precisa alterar")
else:
    print("DESATIVADO - clicando para ativar...")
    
    # Click the toggle
    r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); for (const item of items) { if (item.textContent.toLowerCase().includes('retirada')) { const toggle = item.querySelector('.eds-switch'); if (toggle) { toggle.click(); return 'clicked'; } } } return 'not found'; }()""", "returnByValue": True})
    click_result = ((r.get("result") or {}).get("value", "") if r else "")
    print(f"  Toggle click: {click_result}")
    time.sleep(2)
    
    # Verify toggle state changed
    r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); for (const item of items) { if (item.textContent.toLowerCase().includes('retirada')) { const toggle = item.querySelector('.eds-switch'); if (toggle) { return toggle.className; } } } return 'not found'; }()""", "returnByValue": True})
    after = ((r.get("result") or {}).get("value", "") if r else "")
    print(f"  Toggle class AFTER click: {after}")
    
    if "eds-switch--open" in after:
        print("  TOGGLE ABRIU (ativado)!")
    elif "eds-switch--close" in after:
        print("  TOGGLE FECHOU (desativado?) - pode estar inconsistente")
    
    # Find and click save button
    print("\n  Procurando botao Salvar...")
    r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); for (const el of all) { const t = el.textContent.trim().toLowerCase(); if (t.includes('salvar') && el.children.length === 0) { return el.tagName + ' ' + (el.className||'').substring(0,40) + ' | text=' + t.substring(0,20); } } return 'NOT FOUND'; }()""", "returnByValue": True})
    save_btn = ((r.get("result") or {}).get("value", "") if r else "")
    print(f"  Save text element: {save_btn}")
    
    # Try clicking parent (the actual interactive element)
    r = send("Runtime.evaluate", {"expression": """() => { const all = document.querySelectorAll('*'); for (const el of all) { const t = el.textContent.trim().toLowerCase(); if (t.includes('salvar') && el.children.length === 0) { const parent = el.closest('button, [role="button"], .eds-btn, [class*="btn"], [class*="button"]') || el.parentElement; parent.click(); return parent.tagName + ' ' + (parent.className||'').substring(0,60); } } return 'NOT FOUND'; }()""", "returnByValue": True})
    save_click = ((r.get("result") or {}).get("value", "") if r else "")
    print(f"  Save click: {save_click}")
    
    time.sleep(4)
    
    # Check for success indicator
    r = send("Runtime.evaluate", {"expression": """() => { const body = document.body.innerText; const keywords = ['salvo', 'sucesso', 'atualizado', 'publicado', 'success']; for (const kw of keywords) { if (body.toLowerCase().includes(kw)) { const idx = body.toLowerCase().indexOf(kw); return kw + ' | context: ' + body.substring(Math.max(0,idx-30), idx+80); } } return 'nenhuma confirmacao encontrada'; }()""", "returnByValue": True})
    success = ((r.get("result") or {}).get("value", "") if r else "")
    print(f"  Success indicator: {success[:200]}")
    
    # Check if there's a toast notification
    r = send("Runtime.evaluate", {"expression": """() => { const toasts = document.querySelectorAll('[class*="toast"], [class*="Toast"], [class*="notification"], [class*="Notification"], [class*="message"], [class*="Message"], [class*="snackbar"], [class*="Snackbar"]'); const info = []; for (const t of toasts) { info.push(t.textContent.trim().substring(0,60)); } return JSON.stringify(info); }()""", "returnByValue": True})
    toasts = ((r.get("result") or {}).get("value", "[]") if r else "[]")
    print(f"  Toast/notifications: {toasts}")
    
    # Now VERIFY: navigate away and back to check if change persisted
    print("\n  Verificando persistencia - recarregando pagina...")
    send("Page.navigate", {"url": f"{SELLER_BASE}/"})
    time.sleep(4)
    send("Page.navigate", {"url": f"{SELLER_BASE}/portal/product/{ITEM_ID}"})
    time.sleep(8)
    
    r = send("Runtime.evaluate", {"expression": """(() => { const els = document.querySelectorAll('a, button, div, span, li'); for (const e of els) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return 'ok'; } } return 'NOT FOUND'; })()""", "returnByValue": True})
    time.sleep(4)
    
    r = send("Runtime.evaluate", {"expression": """() => { const items = document.querySelectorAll('.logistics-item'); for (const item of items) { if (item.textContent.toLowerCase().includes('retirada')) { const toggle = item.querySelector('.eds-switch'); return toggle ? toggle.className : 'no-toggle'; } } return 'not-found'; }()""", "returnByValue": True})
    verify = ((r.get("result") or {}).get("value", "") if r else "")
    print(f"  VERIFY after reload: {verify}")
    
    if "eds-switch--open" in verify:
        print("\n✅ SUCESSO! Toggle permaneceu ativado apos recarregar!")
    else:
        print("\n❌ FALHA! Toggle voltou ao estado desativado apos recarregar!")

sock.close()
print("\nTeste concluido.")
