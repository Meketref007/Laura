"""Test toggle + save with proper button click."""
import io, json, ssl, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")
import requests as req, websocket as ws

tabs = req.get("http://127.0.0.1:9222/json", timeout=5).json()
target = next((t for t in tabs if "seller.shopee.com.br" in t.get("url","")), None)
ws_url = target.get("webSocketDebuggerUrl", "")
sock = ws.create_connection(ws_url, timeout=30, sslopt={"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss") else {})
mid = 0
def send(m, p=None):
    global mid; mid += 1
    sock.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        raw = sock.recv(); data = json.loads(raw)
        if data.get("id") == mid: return data

def js(expr, await_promise=True):
    resp = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
    if resp and "result" in resp:
        inner = resp["result"]
        if "exceptionDetails" in inner:
            print(f"  JS Exception: {inner['exceptionDetails'].get('text','')}")
            return None
        return inner.get("result", {}).get("value")
    return None

PRODUCT_ID = "58256032299"
send("Page.enable")
send("Runtime.enable")

# Navigate to product
print("Navigating to product...")
send("Page.navigate", {"url": f"https://seller.shopee.com.br/portal/product/{PRODUCT_ID}"})
time.sleep(7)

# Click Envio
print("Clicking Envio tab...")
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

# Read initial state
initial = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"Initial: {initial}")

# Find save buttons BEFORE toggle
save_btns_before = js("""(function(){var b=document.querySelectorAll('button');var r=[];for(var i=0;i<b.length;i++){var t=b[i].textContent.trim().toLowerCase();if(t.indexOf('salvar')>=0||t.indexOf('aplicar')>=0){r.push({text:b[i].textContent.trim(),disabled:b[i].disabled})}}return JSON.stringify(r)})()""")
print(f"Save buttons before: {save_btns_before}")

# Toggle switch[0] (closed -> open)
print("\nToggling switch[0]...")
js("document.querySelectorAll('.eds-switch')[0].click()")
time.sleep(2)

# Find save buttons AFTER toggle
save_btns_after = js("""(function(){var b=document.querySelectorAll('button');var r=[];for(var i=0;i<b.length;i++){var t=b[i].textContent.trim().toLowerCase();if(t.indexOf('salvar')>=0||t.indexOf('aplicar')>=0){r.push({text:b[i].textContent.trim(),disabled:b[i].disabled})}}return JSON.stringify(r)})()""")
print(f"Save buttons after: {save_btns_after}")

# Click Salvar
print("\nClicking Salvar...")
salvar_clicked = js("""(function(){var btns=document.querySelectorAll('button');for(var i=0;i<btns.length;i++){var txt=btns[i].textContent.trim().toLowerCase();if(txt.indexOf('salvar')>=0||txt.indexOf('aplicar')>=0){btns[i].scrollIntoView();btns[i].click();return true}}return false})()""")
print(f"Salvar clicked: {salvar_clicked}")

# Wait and check for toast/loading
time.sleep(5)

# Check state after save
after_save = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After save: {after_save}")

# Check for success indicators
toast = js("""(function(){var all=document.querySelectorAll('*');for(var i=0;i<all.length;i++){var e=all[i];var t=e.textContent.trim().toLowerCase();if(t.indexOf('sucesso')>=0||t.indexOf('salvo')>=0||t.indexOf('atualizado')>=0){if(e.offsetParent!==null){return e.tagName+' '+(e.className||'').substring(0,40)+' '+t.substring(0,100)}}}return 'none'})()""")
print(f"Success indicator: {toast}")

# RELOAD to verify persistence
print("\nReloading...")
send("Page.reload")
time.sleep(7)

# Click Envio again
js("""(() => { const all = document.querySelectorAll('a, button, [role=tab], span, div, li'); for (const e of all) { if (e.textContent.trim().toLowerCase() === 'envio') { e.click(); return true; } } return false; })()""")
time.sleep(4)

# Final state
final = js("JSON.stringify(Array.from(document.querySelectorAll('.eds-switch')).map(function(s,i){return{idx:i,open:s.classList.contains('eds-switch--open')}}))")
print(f"After reload: {final}")

sock.close()
