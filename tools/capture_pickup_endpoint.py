"""Inspeciona endpoint de retirada automaticamente com timeout."""
import json, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from shopee_agent.seller_center import SellerCenterSession, load_cookies, COOKIES_FILE, SELLER_CENTER_BASE

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
        if request.method == "POST" and "shipping" in url.lower():
            captured.append({
                "url": url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": request.post_data,
            })
            print(f"\n[POST] {url}")

    page.on("request", on_request)

    url = f"{SELLER_CENTER_BASE}/portal/setting/shipping"
    print(f"Abrindo {url}...")
    print("A pagina do Chrome abriu. Va em 'Retirada pelo comprador'")
    print("e ATIVE ou DESATIVE a opcao. O script captura o POST automaticamente.\n")
    print("Aguardando ate 60s por um POST de shipping...\n")

    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # Aguarda captura com timeout
    deadline = time.time() + 60
    while time.time() < deadline:
        if captured:
            break
        time.sleep(0.5)

    if captured:
        print(f"\n=== ENDPOINT CAPTURADO ===")
        for c in captured:
            print(f"\nURL: {c['url']}")
            print(f"Method: {c['method']}")
            if c['post_data']:
                print(f"Body: {c['post_data'][:500]}")

        # Sugere atualizacao dos candidatos no seller_center.py
        print("\n\nPara atualizar os endpoints no codigo:")
        print("  shopee_agent/seller_center.py:")
        for c in captured:
            path = c['url'].replace(SELLER_CENTER_BASE, "")
            print(f"  - {path}")
    else:
        print("\nNenhum POST capturado em 60s.")
        print("Dica: A opcao de retirada pode estar em outra pagina,")
        print("como /portal/setting/shipping/ ou /portal/shipping/")
        print("Tente navegar manualmente para outras paginas de configuracao.")

    browser.close()
