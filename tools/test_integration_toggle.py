"""
Teste de integracao do toggle global no Seller Center real.
Requer: Brave aberto com sessao valida no seller.shopee.com.br

Uso: python tools/test_integration_toggle.py
"""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")

def js(expr, send_func):
    global mid; mid = globals().get("mid", 0) + 1; globals()["mid"] = mid
    send_func(expr)

def create_cdp_connection(tab_id=None):
    tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
    if tab_id:
        target = next((t for t in tabs if t["id"] == tab_id), None)
    else:
        # Prefer shipping-channel tab
        target = next((t for t in tabs if "shipping-channel" in t.get("url","")), None)
        if not target:
            target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
    if not target:
        resp = req.put("http://127.0.0.1:9222/json/new", timeout=10)
        target = resp.json()
    ws_url = target.get("webSocketDebuggerUrl", "")
    sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
    return sock, target

def cdp_send(sock, method, params=None):
    global mid; mid = globals().get("mid", 0) + 1; globals()["mid"] = mid
    sock.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data.get("result")

def cdp_js(sock, expr):
    r = cdp_send(sock, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    if r and "result" in r:
        val = r["result"].get("value")
        exc = r.get("exceptionDetails")
        if exc: return {"error": exc}
        return val
    return None

# ========== TESTS ==========

print("=== Teste de Integracao: Toggle Global ===")
print()

# 1. CDP disponivel
try:
    version = req.get("http://127.0.0.1:9222/json/version", timeout=5)
    test("CDP disponivel", version.status_code == 200)
except Exception as e:
    test("CDP disponivel", False, str(e))
    print("\nAbra o Brave com --remote-debugging-port=9222")
    sys.exit(1)

# 2. Conectar na aba do Seller Center
sock, tab = create_cdp_connection()
test("Conexao WebSocket CDP", sock is not None)
test("Aba do Seller Center encontrada", "seller" in tab.get("url",""), tab.get("url","")[:60])
tab_id = tab["id"]

# 3. Navegar para pagina global de shipping
cdp_send(sock, "Page.enable")
cdp_send(sock, "Runtime.enable")
cdp_send(sock, "Page.navigate", {"url": "https://seller.shopee.com.br/portal/all-settings/shipping/shipping-channel"})
time.sleep(8)

url = cdp_js(sock, "window.location.href")
test("Navegou para shipping-channel", url and "shipping-channel" in url, str(url)[:60])

# 4. Nao foi redirecionado para login
test("Sem redirect para login", url and "login" not in str(url).lower())

# 5. Pagina carregou com switches
switches = cdp_js(sock, "JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(s=>({open:s.classList.contains('eds-switch--open'),disabled:s.classList.contains('eds-switch--disabled')})))")
sw = json.loads(switches) if switches else []
test("Switches encontrados na pagina", len(sw) > 0, f"{len(sw)} switches")

# 6. Fechar dialogs de onboarding
cdp_js(sock, """(() => {
  const all = document.querySelectorAll('button');
  for (const b of all) {
    const t = b.textContent.trim();
    if ((t === 'Ok' || t === 'Done') && b.offsetParent !== null) { b.click(); return 'closed ' + t; }
  }
  return 'no onboarding';
})()""")
time.sleep(1)

# 7. Encontrar canal pelo nome (testar matching)
channels = cdp_js(sock, """JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(sw => {
  const h = sw.closest('.channel-setting-header');
  return { text: h ? h.textContent.trim().substring(0,60) : '(no header)', open: sw.classList.contains('eds-switch--open'), disabled: sw.classList.contains('eds-switch--disabled') };
}))""")
ch = json.loads(channels) if channels else []
test("Channel names encontrados via header", any("Shopee" in c.get("text","") or "Retirada" in c.get("text","") for c in ch), json.dumps([c["text"] for c in ch[:3]]))

# 8. Identificar canal toggleavel (nao disabled)
toggleavel = [c for c in ch if not c["disabled"]]
test("Pelo menos um canal toggleavel encontrado", len(toggleavel) > 0)

# 9. Canal disabled identificado (Retirada pelo Comprador)
disabled_found = any(c["disabled"] for c in ch)
test("Canal disabled identificado", disabled_found, "Retirada pelo Comprador deve ser disabled")

# 10. Testar matching strict (startsWith em vez de includes)
for c in ch:
    txt = c.get("text","").lower().strip()
    if txt.startswith("shopee xpress cpf"):
        test("Matching strict: 'Shopee Xpress CPF' → startsWith OK", True)
        break
else:
    test("Matching strict: 'Shopee Xpress CPF' → encontrado", False)

print()
print(f"Resultado: {PASS} passaram, {FAIL} falharam")

sock.close()
req.delete(f"http://127.0.0.1:9222/json/close/{tab_id}", timeout=5)

if FAIL > 0:
    sys.exit(1)
