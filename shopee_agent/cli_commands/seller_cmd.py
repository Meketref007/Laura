"""Seller Center commands: seller-center-import, seller-center-status, seller-center-browser."""
import json
import sys
from pathlib import Path

from ._utils import print_json


def register_subparsers(sub):
    seller_import = sub.add_parser("seller-center-import", help="Importar cookies do navegador para acessar Central do Vendedor")
    seller_import.add_argument("--cookies-file", default=None, help="Arquivo JSON com cookies (padrao: stdin)")
    seller_import.add_argument("--shop-id", default=None, help="ID da loja (opcional)")
    seller_status = sub.add_parser("seller-center-status", help="Verificar status da sessao da Central do Vendedor")
    seller_status.add_argument("--json", action="store_true", help="Saida em JSON")
    seller_browser = sub.add_parser("seller-center-browser", help="Acessar Central do Vendedor via Playwright (headless browser)")
    seller_browser.add_argument("action", choices=["summarize", "traffic", "shipping", "disputes", "screenshot", "store-setup", "processing", "handle-dispute", "performance", "traffic-data", "update-shipping"], help="Acao a executar")
    seller_browser.add_argument("--visible", action="store_true", help="Modo visivel (nao headless) para debug")
    seller_browser.add_argument("--output", default=None, help="Arquivo de saida para screenshot")
    seller_browser.add_argument("--return-sn", default=None, help="Codigo do retorno/devolucao para handle-dispute")
    seller_browser.add_argument("--dispute-action", choices=["accept", "reject"], default=None, help="Acao na disputa")
    seller_browser.add_argument("--reason", default="", help="Motivo para rejeitar disputa")
    seller_browser.add_argument("--processing-days", type=int, default=None, help="Dias de processamento para update-shipping")


def run(args, client=None, cfg=None):
    if args.command == "seller-center-import":
        from shopee_agent.seller_center import cli_import as _sc_import
        from shopee_agent.seller_center import cli_status as _sc_status
        cookies_path = args.cookies_file
        if cookies_path:
            raw = json.loads(Path(cookies_path).read_text(encoding="utf-8"))
        else:
            raw = json.loads(sys.stdin.read())
        ok = _sc_import(raw, shop_id=args.shop_id)
        if ok:
            print("Cookies importados com sucesso!")
            result = _sc_status()
            print_json(result)
        else:
            print("Falha ao importar cookies")
        return 0 if ok else 1

    if args.command == "seller-center-status":
        from shopee_agent.seller_center import cli_status as _sc_status
        result = _sc_status()
        if args.json:
            print_json(result)
        else:
            authed = result.get("authenticated", False)
            valid = result.get("valid", False)
            print(f"Autenticado: {'SIM' if authed else 'NAO'}")
            print(f"Cookies validos: {'SIM' if valid else 'NAO'}")
            print(f"Cookies salvos: {result.get('cookies_count', 0)}")
            if authed and valid:
                overview = result.get("overview", {})
                health = result.get("health", {})
                print(f"Shop name: {overview.get('shop_name', 'N/A')}")
                print(f"Health score: {health.get('health_score', 'N/A')}")
                print(f"Violacoes ativas: {result.get('violations_count', 0)}")
        return 0

    if args.command == "seller-center-browser":
        import asyncio

        from shopee_agent.seller_center_browser import SellerCenterBrowser

        async def _run_browser():
            async with SellerCenterBrowser(headless=not args.visible) as browser:
                if args.action == "summarize":
                    result = await browser.summarize()
                    print_json(result)
                elif args.action == "traffic":
                    result = await browser.get_traffic_dashboard()
                    print_json(result)
                elif args.action == "shipping":
                    result = await browser.get_shipping_settings()
                    print_json(result)
                elif args.action == "disputes":
                    result = await browser.get_dispute_list()
                    print_json(result)
                elif args.action == "screenshot":
                    out = args.output or "reports/seller_center_screenshot.png"
                    path = await browser.take_screenshot(out)
                    print(f"Screenshot salvo em {path}")
                elif args.action == "store-setup":
                    result = await browser.get_store_setup()
                    print_json(result)
                elif args.action == "processing":
                    result = await browser.get_order_processing_settings()
                    print_json(result)
                elif args.action == "traffic-data":
                    result = await browser.get_traffic_data()
                    print_json(result)
                elif args.action == "performance":
                    result = await browser.get_performance_data()
                    print_json(result)
                elif args.action == "handle-dispute":
                    if not args.return_sn or not args.dispute_action:
                        print("--return-sn e --dispute-action sao obrigatorios")
                        return 1
                    result = await browser.handle_dispute(args.return_sn, args.dispute_action, reason=args.reason)
                    print_json(result)
                elif args.action == "update-shipping":
                    result = await browser.update_shipping_setting(processing_days=args.processing_days)
                    print_json(result)
        asyncio.run(_run_browser())
        return 0

    return 2
