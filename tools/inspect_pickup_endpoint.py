"""
Ferramenta para inspecionar o endpoint de "ativar retirada pelo comprador"
na pagina de configuracoes de envio do Seller Center.

Uso: python tools/inspect_pickup_endpoint.py
Requer: cookies validos do Seller Center, Playwright instalado
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from shopee_agent.seller_center import SellerCenterSession, load_cookies, COOKIES_FILE, SELLER_CENTER_BASE


def inspect():
    session = load_cookies(COOKIES_FILE)
    if not session or not session.is_valid():
        print("Cookies do Seller Center expirados. Rode auto-login primeiro.")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright nao instalado. pip install playwright && playwright install chromium")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Injeta cookies
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

        # Captura requisicoes POST
        captured = []

        def on_request(request):
            if request.method == "POST" and "shipping" in request.url.lower():
                captured.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "post_data": request.post_data,
                })
                print(f"\n>>> POST capturado: {request.url}")
                if request.post_data:
                    print(f"    Body: {request.post_data[:500]}")

        page.on("request", on_request)

        url = f"{SELLER_CENTER_BASE}/portal/setting/shipping"
        print(f"Navegando para {url}...")
        print("A pagina abriu no Chrome. Faca as seguintes acoes:")
        print("  1. Va ate a seção 'Retirada pelo comprador'")
        print("  2. Ative/desative a opcao")
        print("  3. Volte para este terminal")
        print("Pressione Enter quando terminar...\n")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        input()

        if captured:
            print(f"\n{len(captured)} POST(s) capturados:")
            print(json.dumps(captured, indent=2, ensure_ascii=False))
        else:
            print("\nNenhum POST capturado. Tente interagir com a pagina.")

        browser.close()


if __name__ == "__main__":
    inspect()
