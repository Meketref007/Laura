"""Product commands: product-list, product-item-detail, product-item-base-info, product-item-variations, product-set-stock, product-set-price, product-cost-set, product-cost-import, product-margin-review, product-margin-remediate, product-batch-update."""
import concurrent.futures
import csv
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.logger import log_error

from ._utils import (
    append_audit_line,
    coerce_positive_float,
    coerce_positive_int,
    ensure_no_api_error,
    first_present_text,
    normalize_lookup_text,
    print_json,
    refresh_default_access_token,
)


def register_subparsers(sub):
    product_list = sub.add_parser("product-list", help="Lista produtos da loja (wrapper para /api/v2/product/get_item_list)")
    product_list.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_list.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_list.add_argument("--offset", type=int, default=0, help="Offset de paginacao")
    product_list.add_argument("--page-size", type=int, default=20, help="Tamanho da pagina")
    product_list.add_argument("--dry-run", action="store_true", help="Nao chama a API; mostra apenas os parametros previstos")
    product_list.add_argument("--output", help="Arquivo JSON de saida opcional para o preview")
    product_list.add_argument("--item-status", default="NORMAL", choices=["NORMAL", "UNLIST", "BANNED", "DELETED"], help="Status do item para filtro")
    product_item_detail = sub.add_parser("product-item-detail", help="Detalhe completo de um produto (wrapper para /api/v2/product/get_item_detail)")
    product_item_detail.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_item_detail.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_item_detail.add_argument("--item-id", type=int, required=True, help="ID do item")
    product_item_base_info = sub.add_parser("product-item-base-info", help="Informacoes basicas de um produto")
    product_item_base_info.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_item_base_info.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_item_base_info.add_argument("--item-id", type=int, required=True, help="ID do item")
    product_item_variations = sub.add_parser("product-item-variations", help="Variacoes (SKUs) de um produto")
    product_item_variations.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_item_variations.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_item_variations.add_argument("--item-id", type=int, required=True, help="ID do item")
    product_set_stock = sub.add_parser("product-set-stock", help="Atualiza estoque de um item ou variação")
    product_set_stock.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_set_stock.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_set_stock.add_argument("--item-id", type=int, required=True, help="ID do item")
    product_set_stock.add_argument("--variation-id", type=int, default=None, help="ID da variação (opcional)")
    product_set_stock.add_argument("--stock", type=int, required=True, help="Novo nível de estoque")
    product_set_stock.add_argument("--dry-run", action="store_true", help="Não executa a alteração; apenas mostra o payload")
    product_set_price = sub.add_parser("product-set-price", help="Atualiza preço de um item ou variação")
    product_set_price.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_set_price.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_set_price.add_argument("--item-id", type=int, required=True, help="ID do item")
    product_set_price.add_argument("--variation-id", type=int, default=None, help="ID da variação (opcional)")
    product_set_price.add_argument("--price", type=float, required=True, help="Novo preço (na mesma unidade usada pela API)")
    product_set_price.add_argument("--dry-run", action="store_true", help="Não executa a alteração; apenas mostra o payload")
    product_cost_set = sub.add_parser("product-cost-set", help="Define custo (COGS) para um item/variação")
    product_cost_set.add_argument("--item-id", required=True, help="ID do item ou SKU")
    product_cost_set.add_argument("--cost", required=True, help="Custo por unidade (ex: 15.50)")
    product_cost_set.add_argument("--dry-run", action="store_true", help="Não executa a alteração; apenas mostra o payload")
    product_cost_import = sub.add_parser("product-cost-import", help="Importa custos em lote a partir de CSV/JSON")
    product_cost_import.add_argument("--file", required=True, help="Arquivo CSV/JSON com colunas item_id, variation_id, sku, item_name, cost")
    product_cost_import.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_cost_import.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_cost_import.add_argument("--resolve-with-shop", action="store_true", help="Usa product-list/item-detail para casar SKU/nome")
    product_cost_import.add_argument("--max-items", type=int, default=500, help="Limite de itens lidos do catálogo da loja")
    product_cost_import.add_argument("--dry-run", action="store_true", help="Não grava nada; apenas mostra o resumo")
    product_margin_review = sub.add_parser("product-margin-review", help="Revisa margens dos produtos com base em custos cadastrados")
    product_margin_review.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_margin_review.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_margin_review.add_argument("--low-margin-threshold", type=float, default=0.20, help="Margem minima aceitavel em decimal")
    product_margin_review.add_argument("--target-margin-floor", type=float, default=0.25, help="Margem alvo usada para sugerir preco minimo")
    product_margin_review.add_argument("--max-items", type=int, default=200, help="Limite de itens a revisar")
    product_margin_review.add_argument("--page-size", type=int, default=50, help="Tamanho da pagina do catálogo")
    product_margin_review.add_argument("--output", default="reports/laura_product_margin_review_latest.json", help="Arquivo JSON de saída")
    product_margin_remediate = sub.add_parser("product-margin-remediate", help="Gera revisão de margem, cria caso de remediação e notifica Telegram")
    product_margin_remediate.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_margin_remediate.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_margin_remediate.add_argument("--low-margin-threshold", type=float, default=0.20, help="Margem minima aceitavel em decimal")
    product_margin_remediate.add_argument("--target-margin-floor", type=float, default=0.25, help="Margem alvo usada para sugerir preco minimo")
    product_margin_remediate.add_argument("--max-items", type=int, default=200, help="Limite de itens a revisar")
    product_margin_remediate.add_argument("--page-size", type=int, default=50, help="Tamanho da pagina do catálogo")
    product_margin_remediate.add_argument("--output", default="reports/laura_product_margin_review_latest.json", help="Arquivo JSON de saída")
    product_margin_remediate.add_argument("--dry-run", action="store_true", help="Não notifica Telegram nem cria caso; apenas gera o relatório")
    product_batch = sub.add_parser("product-batch-update", help="Apply batch updates (CSV) for stock/price with concurrency")
    product_batch.add_argument("--file", required=True, help="CSV file with columns: item_id,variation_id,stock,price")
    product_batch.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    product_batch.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    product_batch.add_argument("--concurrency", type=int, default=4, help="Number of worker threads to use")
    product_batch.add_argument("--rate-delay", type=float, default=0.0, help="Delay seconds between requests per worker")
    product_batch.add_argument("--dry-run", action="store_true", help="Do not call API; only show planned actions")
    product_batch.add_argument("--backup-file", default=None, help="Path to write JSONL backup of previous values before update")


def run(args, client=None, cfg=None):
    from shopee_agent.config import ConfigError, load_config
    if cfg is None:
        try:
            cfg = load_config()
        except ConfigError as exc:
            log_error("Config load failed", error=str(exc))
            print(str(exc), file=sys.stderr)
            return 1
    if client is None:
        from shopee_agent.client import ShopeeClient
        client = ShopeeClient(cfg)

    if args.command == "product-list":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if getattr(args, "dry_run", False):
            preview = {"command": "product-list", "offset": args.offset, "page_size": args.page_size, "item_status": args.item_status, "shop_id": effective_shop_id, "has_access_token": bool(effective_access_token)}
            if args.output:
                Path(args.output).write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Preview salvo em: {args.output}")
            else:
                print_json(preview)
            return 0
        if not effective_access_token:
            print("Missing access token (use --access-token or SHOPEE_DEFAULT_ACCESS_TOKEN)", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id (use --shop-id or SHOPEE_DEFAULT_SHOP_ID)", file=sys.stderr); return 1
        if args.offset < 0:
            print("--offset deve ser >= 0", file=sys.stderr); return 1
        if args.page_size < 1 or args.page_size > 100:
            print("--page-size deve estar entre 1 e 100", file=sys.stderr); return 1
        if args.access_token is None:
            refreshed = refresh_default_access_token(client, cfg)
            if refreshed:
                effective_access_token = refreshed
        resp = client.get_item_list(access_token=effective_access_token, shop_id=effective_shop_id, offset=args.offset, page_size=args.page_size, item_status=args.item_status)
        err = ensure_no_api_error(resp.data, "product-list")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        return 0

    if args.command == "product-item-detail":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        resp = client.get_item_detail(access_token=effective_access_token, shop_id=effective_shop_id, item_id=args.item_id)
        err = ensure_no_api_error(resp.data, "product-item-detail")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        return 0

    if args.command == "product-item-base-info":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        resp = client.get_item_base_info(access_token=effective_access_token, shop_id=effective_shop_id, item_id=args.item_id)
        err = ensure_no_api_error(resp.data, "product-item-base-info")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        return 0

    if args.command == "product-item-variations":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        resp = client.get_item_variations(access_token=effective_access_token, shop_id=effective_shop_id, item_id=args.item_id)
        err = ensure_no_api_error(resp.data, "product-item-variations")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        return 0

    if args.command == "product-set-stock":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        payload = {"item_id": args.item_id, "variation_id": args.variation_id, "stock": args.stock}
        if args.dry_run:
            print("DRY RUN: payload to send:")
            print_json({k: v for k, v in payload.items() if v is not None})
            return 0
        resp = client.update_item_stock(access_token=effective_access_token, shop_id=effective_shop_id, item_id=args.item_id, variation_id=args.variation_id, stock=args.stock)
        err = ensure_no_api_error(resp.data, "product-set-stock")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        append_audit_line(Path("reports/stock_price_changes.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "set_stock", "shop_id": effective_shop_id, "item_id": args.item_id, "variation_id": args.variation_id, "stock": args.stock, "response": resp.data})
        return 0

    if args.command == "product-set-price":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        payload = {"item_id": args.item_id, "variation_id": args.variation_id, "current_price": args.price}
        if args.dry_run:
            print("DRY RUN: payload to send:")
            print_json({k: v for k, v in payload.items() if v is not None})
            return 0
        resp = client.update_item_price(access_token=effective_access_token, shop_id=effective_shop_id, item_id=args.item_id, variation_id=args.variation_id, current_price=args.price)
        err = ensure_no_api_error(resp.data, "product-set-price")
        if err:
            print(err, file=sys.stderr); return 1
        print_json(resp.data)
        append_audit_line(Path("reports/stock_price_changes.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "set_price", "shop_id": effective_shop_id, "item_id": args.item_id, "variation_id": args.variation_id, "price": args.price, "response": resp.data})
        return 0

    if args.command == "product-cost-set":
        if args.dry_run:
            print("DRY RUN: would set cost:")
            print_json({"item_id": args.item_id, "cost": args.cost})
            return 0
        try:
            cost_val = float(args.cost)
        except Exception:
            print("--cost must be a number", file=sys.stderr); return 1
        try:
            _save_product_cost(args.item_id, cost_val)
        except Exception as exc:
            print(f"Failed to save product cost: {exc}", file=sys.stderr); return 1
        append_audit_line(Path("reports/product_costs_audit.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "product_cost_set", "item_id": args.item_id, "cost": cost_val})
        print_json({"status": "ok", "item_id": args.item_id, "cost": cost_val})
        return 0

    if args.command == "product-cost-import":
        source_path = Path(args.file)
        rows = _load_cost_source_rows(source_path)
        lookup = None
        if args.resolve_with_shop:
            effective_access_token = args.access_token or cfg.default_access_token
            effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
            if not effective_access_token:
                print("Missing access token", file=sys.stderr); return 1
            if effective_shop_id is None:
                print("Missing shop id", file=sys.stderr); return 1
            lookup = _build_shop_cost_lookup(client, access_token=effective_access_token, shop_id=effective_shop_id, max_items=max(1, args.max_items))
        summary = _sync_product_cost_rows(rows, lookup=lookup, dry_run=args.dry_run)
        append_audit_line(Path("reports/product_costs_import_audit.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "product_cost_import", "file": str(source_path), "resolve_with_shop": bool(args.resolve_with_shop), "dry_run": bool(args.dry_run), "summary": summary})
        print_json({"status": "ok" if summary["errors"] == [] else "partial", "source": str(source_path), "summary": summary})
        return 0

    if args.command == "product-margin-review":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        if args.low_margin_threshold < 0 or args.low_margin_threshold >= 1:
            print("--low-margin-threshold must be between 0 and 1", file=sys.stderr); return 1
        if args.target_margin_floor <= 0 or args.target_margin_floor >= 1:
            print("--target-margin-floor must be between 0 and 1", file=sys.stderr); return 1
        if args.max_items < 1:
            print("--max-items must be >= 1", file=sys.stderr); return 1
        if args.page_size < 1 or args.page_size > 100:
            print("--page-size deve estar entre 1 e 100", file=sys.stderr); return 1
        report = _build_margin_review_report(client, access_token=effective_access_token, shop_id=effective_shop_id, low_margin_threshold=args.low_margin_threshold, target_margin_floor=args.target_margin_floor, max_items=args.max_items, page_size=args.page_size)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        append_audit_line(Path("reports/laura_product_margin_review_history.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "product_margin_review", "shop_id": effective_shop_id, "output": str(output_path), "low_margin_threshold": args.low_margin_threshold, "target_margin_floor": args.target_margin_floor, "items_seen": report.get("items_seen"), "low_margin_count": report.get("low_margin_count"), "missing_cost_count": report.get("missing_cost_count"), "missing_price_count": report.get("missing_price_count")})
        print_json({"status": "ok", "output": str(output_path), "items_seen": report.get("items_seen"), "low_margin_count": report.get("low_margin_count"), "missing_cost_count": report.get("missing_cost_count"), "missing_price_count": report.get("missing_price_count"), "top_risks": report.get("top_risks", [])[:10]})
        return 0

    if args.command == "product-margin-remediate":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        if args.low_margin_threshold < 0 or args.low_margin_threshold >= 1:
            print("--low-margin-threshold must be between 0 and 1", file=sys.stderr); return 1
        if args.target_margin_floor <= 0 or args.target_margin_floor >= 1:
            print("--target-margin-floor must be between 0 and 1", file=sys.stderr); return 1
        if args.max_items < 1:
            print("--max-items must be >= 1", file=sys.stderr); return 1
        if args.page_size < 1 or args.page_size > 100:
            print("--page-size deve estar entre 1 e 100", file=sys.stderr); return 1
        report = _build_margin_review_report(client, access_token=effective_access_token, shop_id=effective_shop_id, low_margin_threshold=args.low_margin_threshold, target_margin_floor=args.target_margin_floor, max_items=args.max_items, page_size=args.page_size)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        response: dict[str, Any] = {"status": "ok", "output": str(output_path), "items_seen": report.get("items_seen"), "low_margin_count": report.get("low_margin_count"), "missing_cost_count": report.get("missing_cost_count"), "missing_price_count": report.get("missing_price_count")}
        if args.dry_run:
            response["dry_run"] = True
            response["created_case"] = None
            print_json(response)
            return 0
        case = _create_margin_remediation_case(report, reports_dir=output_path.parent)
        notified = _send_telegram_remediation_case(case, reports_dir=output_path.parent)
        response["created_case"] = case.get("case_id")
        response["telegram_notified"] = notified
        response["top_risks"] = report.get("top_risks", [])[:10]
        print_json(response)
        return 0

    if args.command == "product-batch-update":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        rows: list[dict[str, str]] = []
        csv_path = Path(args.file)
        if not csv_path.exists():
            print(f"CSV file not found: {csv_path}", file=sys.stderr); return 1
        with csv_path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                rows.append(r)
        if args.dry_run:
            print(f"DRY RUN: {len(rows)} rows parsed from {csv_path}")
            sample = rows[:5]
            print_json({"rows_count": len(rows), "sample": sample})
            return 0
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        backup_path = Path(args.backup_file) if args.backup_file else None
        if backup_path:
            backup_path.parent.mkdir(parents=True, exist_ok=True)

        def process_row(row: dict[str, str]) -> dict[str, Any]:
            item_id_raw = row.get("item_id", "").strip()
            if not item_id_raw:
                return {"error": "missing item_id", "row": row}
            try:
                item_id = int(item_id_raw)
            except Exception as exc:
                return {"error": f"invalid item_id: {exc}", "row": row}
            var_raw = str(row.get("variation_id", "")).strip()
            variation_id = int(var_raw) if var_raw else None
            stock_raw = str(row.get("stock", "")).strip()
            stock = int(stock_raw) if stock_raw else None
            price_raw = str(row.get("price", "")).strip()
            price = float(price_raw) if price_raw else None
            backup_entry: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), "item_id": item_id, "variation_id": variation_id}
            try:
                detail = client.get_item_detail(access_token=effective_access_token, shop_id=effective_shop_id, item_id=item_id)
                backup_entry["current"] = detail.data if isinstance(detail, type(detail)) else detail.data
            except Exception:
                backup_entry["current"] = None
            if backup_path:
                append_audit_line(backup_path, backup_entry)
            results: dict[str, Any] = {"item_id": item_id, "variation_id": variation_id}
            try:
                if stock is not None:
                    resp_stock = client.update_item_stock(access_token=effective_access_token, shop_id=effective_shop_id, item_id=item_id, variation_id=variation_id, stock=stock)
                    results["stock_response"] = resp_stock.data
                if price is not None:
                    resp_price = client.update_item_price(access_token=effective_access_token, shop_id=effective_shop_id, item_id=item_id, variation_id=variation_id, current_price=price)
                    results["price_response"] = resp_price.data
            except Exception as exc:
                results["error"] = str(exc)
            append_audit_line(Path("reports/stock_price_changes.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "batch_update", "shop_id": effective_shop_id, "row": row, "result": results})
            if args.rate_delay and args.rate_delay > 0:
                try:
                    time.sleep(args.rate_delay)
                except Exception:
                    pass
            return results

        all_results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futures = [ex.submit(process_row, r) for r in rows]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    all_results.append(fut.result())
                except Exception as exc:
                    all_results.append({"error": str(exc)})
        out_path = Path(f"reports/batch_update_results_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(), "results": all_results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote batch update results to {out_path}")
        print_json({"rows": len(rows), "results_file": str(out_path)})
        return 0

    return 2


# --- Product costs helpers ---
_PRODUCT_COSTS_PATH = Path("reports/product_costs.json")


def _load_product_costs() -> dict[str, float]:
    try:
        if not _PRODUCT_COSTS_PATH.exists():
            return {}
        data = json.loads(_PRODUCT_COSTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        normalized: dict[str, float] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                raw_cost = v.get("cost")
            else:
                raw_cost = v
            try:
                normalized[str(k)] = float(raw_cost)
            except Exception:
                continue
        return normalized
    except Exception:
        return {}


def _save_product_cost(item_id: str, cost: float) -> None:
    data = _load_product_costs()
    data[str(item_id)] = float(cost)
    _PRODUCT_COSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PRODUCT_COSTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get_cost_for_item(item_id: str) -> float | None:
    data = _load_product_costs()
    return float(data.get(str(item_id))) if str(item_id) in data else None


def _load_cost_source_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if isinstance(row, dict):
                    rows.append(row)
        return rows
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        rows = []
        for key, value in raw.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("item_id", key)
            else:
                row = {"item_id": key, "cost": value}
            rows.append(row)
        return rows
    raise ValueError(f"Formato de custo nao suportado: {path.suffix or 'unknown'}")


def _build_shop_cost_lookup(client, *, access_token: str, shop_id: int, max_items: int = 500, page_size: int = 100) -> dict[str, str]:
    lookup: dict[str, str] = {}
    seen_items = 0
    offset = 0
    while seen_items < max_items:
        resp = client.get_item_list(access_token=access_token, shop_id=shop_id, offset=offset, page_size=page_size)
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", []) if isinstance(body, dict) else []
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            seen_items += 1
            if seen_items > max_items:
                break
            parent_item_id = first_present_text(item, "item_id", "id")
            if not parent_item_id:
                continue
            item_name = first_present_text(item, "item_name", "name")
            item_sku = first_present_text(item, "item_sku", "sku")
            lookup[f"item_id:{parent_item_id}"] = parent_item_id
            if item_name:
                lookup[f"name:{normalize_lookup_text(item_name)}"] = parent_item_id
            if item_sku:
                lookup[f"sku:{normalize_lookup_text(item_sku)}"] = parent_item_id
            try:
                detail_resp = client.get_item_detail(access_token=access_token, shop_id=shop_id, item_id=int(parent_item_id))
                detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
                if not isinstance(detail_body, dict):
                    continue
                variations = detail_body.get("variation_list") or detail_body.get("model_list") or detail_body.get("variations") or []
                if not isinstance(variations, list):
                    continue
                for variation in variations:
                    if not isinstance(variation, dict):
                        continue
                    variation_id = first_present_text(variation, "variation_id", "model_id", "variationid", "modelid")
                    variation_name = first_present_text(variation, "variation_name", "name", "model_name")
                    variation_sku = first_present_text(variation, "variation_sku", "sku", "model_sku")
                    if variation_id:
                        lookup[f"variation_id:{variation_id}"] = parent_item_id
                    if variation_name:
                        lookup[f"name:{normalize_lookup_text(variation_name)}"] = parent_item_id
                    if variation_sku:
                        lookup[f"sku:{normalize_lookup_text(variation_sku)}"] = parent_item_id
            except Exception:
                continue
        cursor = str(body.get("next_cursor", "") or "") if isinstance(body, dict) else ""
        if not cursor:
            break
        offset += page_size
    return lookup


def _resolve_cost_target(row: dict[str, Any], lookup: dict[str, str] | None = None) -> str | None:
    item_id = first_present_text(row, "item_id", "itemid", "itemId")
    if item_id:
        return item_id
    variation_id = first_present_text(row, "variation_id", "variationid", "variationId")
    if variation_id:
        if lookup:
            target = lookup.get(f"variation_id:{variation_id}")
            if target:
                return target
        return variation_id
    if not lookup:
        return None
    sku = first_present_text(row, "sku", "item_sku", "variation_sku", "model_sku")
    if sku:
        target = lookup.get(f"sku:{normalize_lookup_text(sku)}")
        if target:
            return target
    item_name = first_present_text(row, "item_name", "name", "title", "product_name")
    if item_name:
        target = lookup.get(f"name:{normalize_lookup_text(item_name)}")
        if target:
            return target
    return None


def _sync_product_cost_rows(rows: list[dict[str, Any]], *, lookup: dict[str, str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    summary: dict[str, Any] = {"rows": len(rows), "saved": 0, "skipped": 0, "unmatched": 0, "errors": [], "items": []}
    for row in rows:
        if not isinstance(row, dict):
            summary["skipped"] += 1
            continue
        raw_cost = first_present_text(row, "cost", "cogs", "unit_cost", "purchase_price")
        if not raw_cost:
            summary["skipped"] += 1
            summary["errors"].append({"error": "missing cost", "row": row})
            continue
        try:
            cost_val = float(raw_cost)
        except Exception as exc:
            summary["skipped"] += 1
            summary["errors"].append({"error": f"invalid cost: {exc}", "row": row})
            continue
        target_item_id = _resolve_cost_target(row, lookup)
        if not target_item_id:
            summary["unmatched"] += 1
            summary["errors"].append({"error": "unmatched product", "row": row})
            continue
        if not dry_run:
            _save_product_cost(target_item_id, cost_val)
        summary["saved"] += 1
        summary["items"].append({"item_id": target_item_id, "cost": cost_val, "source_row": row})
    return summary


# --- Margin review helpers ---
def _find_stock_candidate(payload: Any) -> int | None:
    preferred_keys = ("stock", "current_stock", "stock_on_hand", "stock_available", "available_stock", "normal_stock", "quantity", "available_quantity")
    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                candidate = coerce_positive_int(payload.get(key))
                if candidate is not None:
                    return candidate
        for value in payload.values():
            candidate = _find_stock_candidate(value)
            if candidate is not None:
                return candidate
    elif isinstance(payload, list):
        for item in payload:
            candidate = _find_stock_candidate(item)
            if candidate is not None:
                return candidate
    return None


def _find_price_candidate(payload: Any) -> float | None:
    preferred_keys = ("current_price", "sale_price", "price", "shop_price", "model_price", "original_price", "item_price", "display_price")
    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                candidate = coerce_positive_float(payload.get(key))
                if candidate is not None:
                    return candidate
        for value in payload.values():
            candidate = _find_price_candidate(value)
            if candidate is not None:
                return candidate
    elif isinstance(payload, list):
        for item in payload:
            candidate = _find_price_candidate(item)
            if candidate is not None:
                return candidate
    return None


def _build_margin_review_report(client, *, access_token: str, shop_id: int, low_margin_threshold: float = 0.20, target_margin_floor: float = 0.25, max_items: int = 200, page_size: int = 50) -> dict[str, Any]:
    items_seen = 0
    reviewed_entries: list[dict[str, Any]] = []
    low_margin_entries: list[dict[str, Any]] = []
    missing_cost_entries: list[dict[str, Any]] = []
    missing_price_entries: list[dict[str, Any]] = []
    cursor = 0
    while items_seen < max_items:
        resp = client.get_item_list(access_token=access_token, shop_id=shop_id, offset=cursor, page_size=page_size)
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", []) if isinstance(body, dict) else []
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            items_seen += 1
            if items_seen > max_items:
                break
            item_id = first_present_text(item, "item_id", "id")
            if not item_id:
                continue
            item_name = first_present_text(item, "item_name", "name") or f"item-{item_id}"
            try:
                detail_resp = client.get_item_detail(access_token=access_token, shop_id=shop_id, item_id=int(item_id))
                detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
            except Exception:
                detail_body = item
            variations = detail_body.get("variation_list") or detail_body.get("model_list") or detail_body.get("variations") or []
            if not isinstance(variations, list) or not variations:
                variations = [detail_body]
            for variation in variations:
                if not isinstance(variation, dict):
                    continue
                variation_id = first_present_text(variation, "variation_id", "model_id", "variationid", "modelid")
                variation_name = first_present_text(variation, "variation_name", "name", "model_name") or item_name
                variation_sku = first_present_text(variation, "variation_sku", "sku", "model_sku")
                price = _find_price_candidate(variation)
                cost = _get_cost_for_item(item_id)
                entry: dict[str, Any] = {"item_id": item_id, "item_name": item_name, "variation_id": variation_id or None, "variation_name": variation_name, "sku": variation_sku or None, "price": round(price, 2) if price is not None else None, "cost": round(cost, 2) if cost is not None else None}
                if price is None:
                    entry["status"] = "missing_price"
                    missing_price_entries.append(entry)
                    reviewed_entries.append(entry)
                    continue
                if cost is None:
                    entry["status"] = "missing_cost"
                    missing_cost_entries.append(entry)
                    reviewed_entries.append(entry)
                    continue
                margin_ratio = (price - cost) / price if price > 0 else None
                entry["margin_pct"] = round((margin_ratio or 0.0) * 100, 2) if margin_ratio is not None else None
                recommended_price = cost / (1 - target_margin_floor) if 0 < target_margin_floor < 1 else None
                entry["recommended_price"] = round(recommended_price, 2) if recommended_price is not None else None
                if margin_ratio is not None and margin_ratio < low_margin_threshold:
                    entry["status"] = "negative_margin" if margin_ratio <= 0 else "low_margin"
                    low_margin_entries.append(entry)
                else:
                    entry["status"] = "ok"
                reviewed_entries.append(entry)
        cursor += page_size
        if not body.get("has_next_page"):
            break
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "shop_id": shop_id,
        "low_margin_threshold": low_margin_threshold,
        "target_margin_floor": target_margin_floor,
        "items_seen": items_seen,
        "reviewed_count": len(reviewed_entries),
        "ok_count": sum(1 for entry in reviewed_entries if entry.get("status") == "ok"),
        "low_margin_count": len(low_margin_entries),
        "missing_cost_count": len(missing_cost_entries),
        "missing_price_count": len(missing_price_entries),
        "top_risks": sorted([entry for entry in low_margin_entries if entry.get("margin_pct") is not None], key=lambda entry: entry.get("margin_pct", 0.0))[:20],
        "reviewed_entries": reviewed_entries,
        "low_margin_entries": low_margin_entries,
        "missing_cost_entries": missing_cost_entries,
        "missing_price_entries": missing_price_entries,
    }


def _create_margin_remediation_case(report: dict[str, Any], *, reports_dir: Path) -> dict[str, Any]:
    top_risks = report.get("top_risks", []) if isinstance(report.get("top_risks"), list) else []
    case_id = f"protect_margin-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    case = {"case_id": case_id, "action_key": "protect_margin", "title": "Protect Margin", "created_at": datetime.now(UTC).isoformat(), "executed": False, "execute_on_approve": True, "payload": top_risks, "report_path": str(reports_dir / "laura_product_margin_review_latest.json"), "report_summary": {"items_seen": report.get("items_seen"), "reviewed_count": report.get("reviewed_count"), "low_margin_count": report.get("low_margin_count"), "missing_cost_count": report.get("missing_cost_count"), "missing_price_count": report.get("missing_price_count")}}
    cases_path = reports_dir / "laura_remediation_cases.jsonl"
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    with cases_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {"timestamp": datetime.now(UTC).isoformat(), "action": "create_margin_remediation_case", "case_id": case_id, "items": len(top_risks), "report_path": case["report_path"]})
    return case


def _send_telegram_remediation_case(case: dict[str, Any], *, reports_dir: Path) -> bool:
    token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    top_risks = case.get("payload", []) if isinstance(case.get("payload"), list) else []
    lines = ["Laura Margin Review", f"Case: {case.get('case_id')}", f"Ação: {case.get('action_key')}", f"Itens críticos: {len(top_risks)}"]
    for entry in top_risks[:5]:
        if not isinstance(entry, dict):
            continue
        label = entry.get("variation_name") or entry.get("item_name") or entry.get("item_id") or "item"
        lines.append(f"- {label}: preço={entry.get('price')} custo={entry.get('cost')} margem={entry.get('margin_pct')}% alvo={entry.get('recommended_price')}")
    keyboard = {"inline_keyboard": [[{"text": "Aprovar", "callback_data": f"approve:{case['case_id']}"}, {"text": "Cancelar", "callback_data": f"cancel:{case['case_id']}"}]]}
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": "\n".join(lines), "reply_markup": json.dumps(keyboard, ensure_ascii=False), "disable_web_page_preview": True}, timeout=10)
        append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {"timestamp": datetime.now(UTC).isoformat(), "action": "notify_margin_remediation_case", "case_id": case.get("case_id"), "top_risks": len(top_risks)})
        return True
    except Exception:
        return False
