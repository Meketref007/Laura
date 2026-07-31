"""Navega para pagina de config de envio e captura TODAS as requests (GET+POST)."""
import json, sys, time
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from shopee_agent.seller_center import load_cookies, COOKIES_FILE, SELLER_CENTER_BASE

session = load_cookies(COOKIES_FILE)
if not session or not session.is_valid():
    print("Cookies expirados.")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright nao instalado.")
    sys.exit(1)

captured = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    for c in session.cookies:
        if c.is_expired():
            continue
        try:
            context.add_cookies([{
                "name": c.name,
                "value": c.value,
                "domain": c.domain.lstrip("."),
                "path": c.path or "/",
                "secure": c.secure,
            }])
        except Exception:
            pass

    def on_request(request):
        url = request.url
        # Captura apenas requests para o seller.shopee.com.br
        if "seller.shopee.com.br" in url and "/api/" in url:
            captured.append({
                "url": url,
                "method": request.method,
                "post_data": request.post_data[:500] if request.post_data else None,
            })
            print(f"[{request.method}] {url}")

    page.on("request", on_request)

    print("Navegando para configuracao de envio...")
    print("O script captura TODAS as requests API do Seller Center.")
    print("Navegue ate a pagina de configuracao de envio e procure")
    print("pela opcao 'Retirada pelo comprador'.")
    print("Fechando o navegador automaticamente apos 5 minutos.\n")

    page.goto(f"{SELLER_CENTER_BASE}/portal/setting/shipping", wait_until="domcontentloaded", timeout=30000)

    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            page.title()
        except:
            break

    if captured:
        print(f"\n\n=== {len(captured)} REQUISICOES CAPTURADAS ===")
        # Filtra por shipping/setting/pickup
        shipping = [c for c in captured if any(w in c['url'].lower() for w in ['shipping','setting','pickup','logistics','delivery','retirada'])]
        if shipping:
            print(f"\n--- SHIPPING/SETTING ({len(shipping)}) ---")
            for c in shipping:
                print(json.dumps(c, indent=2, ensure_ascii=False))
        else:
            print("\nNenhuma requisicao de shipping encontrada.")
            print("Todas as requisicoes capturadas:")
            for c in captured:
                print(f"  [{c['method']}] {c['url']}")
    else:
        print("\nNenhuma requisicao capturada.")

    browser.close()
