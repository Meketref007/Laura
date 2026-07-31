"""Captura TODOS os POSTs do Seller Center, nao apenas shipping.
Fica aberto por 5 minutos. Navegue manualmente ate a config de retirada."""
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
        if request.method not in ("POST", "PUT"):
            return
        url = request.url
        captured.append({
            "url": url,
            "method": request.method,
            "post_data": request.post_data[:1000] if request.post_data else None,
        })
        print(f"\n[{request.method}] {url}")
        if request.post_data:
            print(f"    Body: {request.post_data[:200]}")

    page.on("request", on_request)

    # Abre a pagina inicial do Seller Center primeiro
    print("Abrindo Seller Center...")
    print("Navegue manualmente ate a pagina de configuracao de envio")
    print("e ATIVE/DESATIVE a opcao 'Retirada pelo comprador'.")
    print("O script ficara aberto por 10 minutos capturando requisicoes.\n")

    print("DICA: Tente acessar estas URLs manualmente no navegador:")
    print("  " + SELLER_CENTER_BASE + "/portal/all-settings/shipping/preferred-pickup-time/edit")
    print("  " + SELLER_CENTER_BASE + "/portal/logistics/setup-pickup-time")
    print("  " + SELLER_CENTER_BASE + "/portal/setting/shipping")
    print()

    page.goto(SELLER_CENTER_BASE, wait_until="domcontentloaded", timeout=30000)

    deadline = time.time() + 600  # 10 minutos
    while time.time() < deadline:
        if captured:
            # Mostra preview a cada nova captura
            pass
        time.sleep(0.5)
        try:
            page.title()
        except:
            print("Browser fechado.")
            break

    if captured:
        print(f"\n\n=== {len(captured)} REQUISICOES CAPTURADAS ===")
        print(json.dumps(captured, indent=2, ensure_ascii=False))

        # Endpoints que contem pickup/retirada
        pickup = [c for c in captured if any(w in c['url'].lower() for w in ['pickup', 'retirada'])]
        if pickup:
            print(f"\n\n=== ENDPOINTS DE RETIRADA ENCONTRADOS ===")
            print(json.dumps(pickup, indent=2, ensure_ascii=False))
        else:
            print("\nNenhum endpoint com 'pickup'/'retirada' encontrado.")
            print("Todos os endpoints capturados estao acima.")
    else:
        print("\nNenhuma requisicao capturada em 5 minutos.")

    browser.close()
