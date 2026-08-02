"""Monitoring & Misc commands: inventory-monitor, orders-notify-poll, ratings-backfill, store-health-report, store-analysis, visual-analysis, alerts, perf-benchmark."""
import concurrent.futures
import json
import os
import statistics as _statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shopee_agent.logger import info, log_error

from ._utils import (
    append_audit_line,
    coerce_positive_float,
    coerce_positive_int,
    print_json,
    refresh_default_access_token,
)


def register_subparsers(sub):
    inventory_monitor = sub.add_parser("inventory-monitor", help="Monitor de estoque local com alertas para produtos abaixo do limite")
    inventory_monitor.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    inventory_monitor.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    inventory_monitor.add_argument("--low-stock-threshold", type=int, default=5, help="Items below this stock count as low-stock")
    inventory_monitor.add_argument("--max-items", type=int, default=50, help="Max items to inspect per run")
    inventory_monitor.add_argument("--page-size", type=int, default=50, help="Page size for product queries")
    inventory_monitor.add_argument("--dry-run", action="store_true", help="Do not call API; simulate only")
    orders_notify_poll = sub.add_parser("orders-notify-poll", help="Polling fallback para notificar novos pedidos quando webhook falhar")
    orders_notify_poll.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    orders_notify_poll.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    orders_notify_poll.add_argument("--window-minutes", type=int, default=180, help="Janela de busca de pedidos recentes")
    orders_notify_poll.add_argument("--page-size", type=int, default=50, help="Page size para consulta")
    orders_notify_poll.add_argument("--max-orders", type=int, default=100, help="Limite de pedidos por execução")
    orders_notify_poll.add_argument("--dry-run", action="store_true", help="Não envia notificação, só mostra prévia")
    ratings_backfill = sub.add_parser("ratings-backfill", help="Process all pending unanswered ratings retroactively")
    ratings_backfill.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    ratings_backfill.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    ratings_backfill.add_argument("--lookback-days", type=int, default=60, help="How many days back to look for unresponded ratings")
    ratings_backfill.add_argument("--batch-size", type=int, default=50, help="Page size for API calls")
    ratings_backfill.add_argument("--dry-run", action="store_true", help="Do not send responses, show preview only")
    store_health = sub.add_parser("store-health-report", help="Generate executive store health report (inventory, performance, recent activity)")
    store_health.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    store_health.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    store_health.add_argument("--low-stock-threshold", type=int, default=5, help="Items below this stock count as low-stock")
    store_health.add_argument("--days", type=int, default=7, help="Days window for order analysis")
    store_health.add_argument("--dry-run", action="store_true", help="Do not call API; simulate only")
    store_analysis = sub.add_parser("store-analysis", help="Run LLM-driven store analysis using Ollama")
    store_analysis.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    store_analysis.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    store_analysis.add_argument("--prompt-type", choices=["general_agent", "triage", "product_diagnosis", "daily_report"], default="general_agent", help="Which LLM prompt template to use")
    store_analysis.add_argument("--model", default=None, help="Ollama model to use; uses LAURA_LLM_MODEL env if unset")
    store_analysis.add_argument("--days", type=int, default=1, help="Days window for analysis")
    store_analysis.add_argument("--dry-run", action="store_true", help="Do not call LLM; show input data only")
    store_analysis.add_argument("--vision", action="store_true", help="Run visual analysis on product images (OCR + quality)")
    store_analysis.add_argument("--no-cache", action="store_true", help="Ignore cached data and force API re-query")
    store_analysis.add_argument("--ttl-days", type=int, default=30, help="Cache TTL in days (default: 30)")
    visual_analysis = sub.add_parser("visual-analysis", help="Analisar qualidade visual de imagens de produtos")
    visual_analysis.add_argument("paths", nargs="+", help="Image files or directories to analyze")
    visual_analysis.add_argument("--no-ocr", action="store_true", help="Disable OCR even if pytesseract is available")
    visual_analysis.add_argument("--output", default=None, help="Optional JSON output file")
    visual_analysis.add_argument("--format", choices=["json", "text"], default="json", help="Output format for stdout")
    perf_bench = sub.add_parser("perf-benchmark", help="Run simple performance benchmark against Shopee endpoints")
    perf_bench.add_argument("--endpoint", choices=["product-list","order-list"], default="product-list", help="Endpoint to test")
    perf_bench.add_argument("--iterations", type=int, default=10, help="Total calls per worker")
    perf_bench.add_argument("--concurrency", type=int, default=2, help="Number of concurrent workers")
    perf_bench.add_argument("--page-size", type=int, default=1, help="Page size for product/order queries")
    perf_bench.add_argument("--dry-run", action="store_true", help="Don't call the API; just simulate timings")
    alerts_cmd = sub.add_parser("alerts", help="Manage alerts: view history, test rules, send test webhooks")
    alerts_subcommand = alerts_cmd.add_subparsers(dest="alerts_action", required=False)
    alerts_history = alerts_subcommand.add_parser("history", help="View alert history")
    alerts_history.add_argument("--limit", type=int, default=20, help="Number of recent alerts to show")
    alerts_history.add_argument("--rule", help="Filter by specific rule")
    alerts_history.add_argument("--severity", choices=["CRITICAL", "WARNING", "INFO"], help="Filter by severity")


def run(args, client=None, cfg=None):
    from shopee_agent.config import ConfigError, load_config
    if args.command in ("visual-analysis", "alerts"):
        cfg = None
        client = None
    elif cfg is None:
        try:
            cfg = load_config()
        except ConfigError as exc:
            log_error("Config load failed", error=str(exc))
            print(str(exc), file=sys.stderr)
            return 1
    if client is None and args.command not in ("visual-analysis", "alerts"):
        from shopee_agent.client import ShopeeClient
        client = ShopeeClient(cfg)

    if args.command == "inventory-monitor":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        if args.access_token is None:
            refreshed = refresh_default_access_token(client, cfg)
            if refreshed:
                effective_access_token = refreshed
        if args.dry_run:
            preview = {"shop_id": effective_shop_id, "low_stock_threshold": args.low_stock_threshold, "max_items": args.max_items, "page_size": args.page_size, "output": "reports/laura_inventory_monitor_latest.json"}
            print("DRY RUN: inventory-monitor preview:")
            print_json(preview)
            return 0
        try:
            report = _build_stock_monitor_report(client, access_token=effective_access_token, shop_id=effective_shop_id, low_stock_threshold=args.low_stock_threshold, max_items=args.max_items, page_size=args.page_size)
        except Exception as exc:
            print(f"Inventory monitor failed: {exc}", file=sys.stderr); return 1
        out_path = Path("reports/laura_inventory_monitor_latest.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            if report.get("low_stock_count", 0) > 0:
                from shopee_agent.telegram_narrator import narrador
                narrador.alerta("Estoque baixo detectado", detalhe=f"{report['low_stock_count']} item(ns) abaixo do limite `{args.low_stock_threshold}`. Relatório salvo em `{out_path}`")
        except Exception:
            pass
        print_json(report)
        return 0

    if args.command == "orders-notify-poll":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        if args.access_token is None:
            refreshed = refresh_default_access_token(client, cfg)
            if refreshed:
                effective_access_token = refreshed
        from shopee_agent.telegram_narrator import narrador
        state_path = Path("reports/laura_notified_orders.state")
        notified: set[str] = set()
        if state_path.exists():
            try:
                for raw in state_path.read_text(encoding="utf-8").splitlines():
                    value = raw.strip()
                    if value:
                        notified.add(value)
            except Exception:
                pass
        now = datetime.now(UTC)
        time_to = int(now.timestamp())
        time_from = int((now - timedelta(minutes=max(5, args.window_minutes))).timestamp())
        cursor = ""
        seen = 0
        new_orders: list[dict[str, Any]] = []
        while seen < args.max_orders:
            resp = client.get_order_list(access_token=effective_access_token, shop_id=effective_shop_id, time_from=time_from, time_to=time_to, page_size=args.page_size, cursor=cursor)
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            orders = body.get("order_list", []) if isinstance(body, dict) else []
            if not orders:
                break
            for order in orders:
                if not isinstance(order, dict):
                    continue
                seen += 1
                if seen > args.max_orders:
                    break
                order_sn = _order_sn_from_payload(order)
                if not order_sn:
                    continue
                if order_sn in notified:
                    continue
                amount = _find_revenue_candidate(order) or 0.0
                new_orders.append({"order_sn": order_sn, "amount": round(float(amount), 2)})
            cursor = str(body.get("next_cursor", "") or "") if isinstance(body, dict) else ""
            if not cursor:
                break
        if args.dry_run:
            print_json({"window_minutes": args.window_minutes, "seen": seen, "new_orders_count": len(new_orders), "new_orders_sample": new_orders[:10]})
            return 0
        for entry in new_orders:
            narrador.novo_pedido(entry["order_sn"], float(entry.get("amount", 0.0) or 0.0))
            notified.add(entry["order_sn"])
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("\n".join(sorted(notified)) + ("\n" if notified else ""), encoding="utf-8")
        except Exception:
            pass
        append_audit_line(Path("reports/laura_orders_notify_poll_audit.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "window_minutes": args.window_minutes, "seen": seen, "new_orders_count": len(new_orders), "new_orders": new_orders[:20]})
        print_json({"status": "ok", "seen": seen, "new_orders_count": len(new_orders), "state_file": str(state_path), "audit_file": "reports/laura_orders_notify_poll_audit.jsonl"})
        return 0

    if args.command == "ratings-backfill":
        from shopee_agent.auto_responses import process_ratings_backfill
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        if args.dry_run:
            info(f"ratings-backfill --dry-run: would process {args.lookback_days} days, batch={args.batch_size}")
            print_json({"status": "dry_run", "lookback_days": args.lookback_days, "batch_size": args.batch_size})
            return 0
        try:
            stats = process_ratings_backfill(client=client, access_token=effective_access_token, shop_id=effective_shop_id, lookback_days=args.lookback_days, batch_size=args.batch_size)
            print_json(stats)
            return 0
        except Exception as exc:
            log_error(f"ratings-backfill failed: {exc}")
            print_json({"status": "error", "error": str(exc)})
            return 1

    if args.command == "store-health-report":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if args.dry_run:
            print("DRY RUN: store-health-report simulation")
            print_json({"simulation": True, "days": args.days, "low_stock_threshold": args.low_stock_threshold})
            return 0
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        if args.access_token is None:
            refreshed = refresh_default_access_token(client, cfg)
            if refreshed:
                effective_access_token = refreshed
        report: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "shop_id": effective_shop_id, "sections": {}}
        try:
            now = int(time.time())
            time_from = int((datetime.now(UTC) - timedelta(days=args.days)).timestamp())
            resp_orders = client.get_order_list(access_token=effective_access_token, shop_id=effective_shop_id, time_from=time_from, time_to=now, page_size=100)
            body = resp_orders.data.get("response", {}) if isinstance(resp_orders.data, dict) else {}
            orders = body.get("order_list", [])
            report["sections"]["orders"] = {"count": len(orders), "window_days": args.days, "sample": orders[:3] if orders else []}
        except Exception as exc:
            report["sections"]["orders"] = {"error": str(exc)}
        try:
            report["sections"]["inventory"] = _build_stock_monitor_report(client, access_token=effective_access_token, shop_id=effective_shop_id, low_stock_threshold=args.low_stock_threshold, max_items=200, page_size=50)
        except Exception as exc:
            report["sections"]["inventory"] = {"error": str(exc)}
        report["sections"]["api_health"] = {"orders_ok": "error" not in str(report["sections"].get("orders", {})), "inventory_ok": "error" not in str(report["sections"].get("inventory", {}))}
        report["overall_status"] = "healthy" if all("error" not in str(v) for v in report["sections"].values()) else "warning"
        out_path = Path(f"reports/store_health_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote store health report to {out_path}")
        print_json(report)
        return 0

    if args.command == "store-analysis":
        import shopee_agent.api_cache as api_cache
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        analysis_data: dict[str, Any] = {"shop_id": effective_shop_id, "generated_at": datetime.now(UTC).isoformat()}
        cache_name = f"store_analysis_{effective_shop_id}"
        if not args.no_cache and api_cache.is_fresh(cache_name, ttl_days=args.ttl_days):
            cached = api_cache.load(cache_name)
            if cached:
                analysis_data = cached
                print(f"Usando dados em cache ({api_cache.age(cache_name):.0f}d atrás). Use --no-cache para forçar reconsulta.", file=sys.stderr)
        if args.no_cache or not api_cache.is_fresh(cache_name, ttl_days=args.ttl_days):
            if args.access_token is None:
                refreshed = refresh_default_access_token(client, cfg)
                if refreshed:
                    effective_access_token = refreshed
            try:
                now = int(time.time())
                time_from = int((datetime.now(UTC) - timedelta(days=args.days)).timestamp())
                resp_orders = client.get_order_list(access_token=effective_access_token, shop_id=effective_shop_id, time_from=time_from, time_to=now, page_size=50)
                body_orders = resp_orders.data.get("response", {}) if isinstance(resp_orders.data, dict) else {}
                orders = body_orders.get("order_list", [])
                analysis_data["orders_count"] = len(orders)
                analysis_data["orders_sample"] = orders[:5] if orders else []
                resp_products = client.get_item_list(access_token=effective_access_token, shop_id=effective_shop_id, offset=0, page_size=20)
                body_products = resp_products.data.get("response", {}) if isinstance(resp_products.data, dict) else {}
                products = body_products.get("item", [])
                analysis_data["products_count"] = len(products)
                analysis_data["products_sample"] = products[:3] if products else []
                if args.vision and products:
                    try:
                        from shopee_agent.vision_analysis import analyze_items_visuals
                        vision_ctx = analyze_items_visuals(products, max_items=3, max_images_per_item=1, perform_ocr=not args.no_ocr)
                        if vision_ctx:
                            analysis_data["vision_context"] = vision_ctx
                            print("Vision analysis complete", file=sys.stderr)
                    except Exception as ve:
                        print(f"Vision analysis warning: {ve}", file=sys.stderr)
            except Exception as exc:
                analysis_data["error"] = f"Failed to fetch data: {str(exc)}"
        if "error" not in analysis_data:
            try:
                api_cache.save(cache_name, analysis_data, ttl_days=args.ttl_days)
            except Exception:
                pass
        if args.dry_run:
            print("DRY RUN: store-analysis input data:", file=sys.stderr)
            print_json(analysis_data)
            return 0
        model_name = args.model or os.getenv("LAURA_LLM_MODEL", "llama3.2:3b")
        try:
            from shopee_agent.llm_local import create_analyzer
            analyzer = create_analyzer(model_name)
            analysis_result = analyzer.analyze(metrics=analysis_data, prompt_type=args.prompt_type, fallback_on_error=True)
            out_path = Path(f"reports/store_analysis_{args.prompt_type}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({"input": analysis_data, "analysis": analysis_result}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Wrote analysis to {out_path}", file=sys.stderr)
            print_json(analysis_result)
            return 0
        except Exception as exc:
            print(f"LLM analysis failed: {str(exc)}", file=sys.stderr); return 1

    if args.command == "visual-analysis":
        from shopee_agent.vision_analysis import MarketplaceVisionAnalyzer, dump_visual_report
        analyzer = MarketplaceVisionAnalyzer()
        report = analyzer.analyze_paths(args.paths, perform_ocr=not args.no_ocr)
        if args.output:
            output_path = dump_visual_report(report, args.output)
            print(f"Wrote visual analysis to {output_path}")
        if args.format == "text":
            print("Laura visual analysis")
            print("=" * 60)
            print(f"Images analyzed: {report.total_images}")
            print(f"Thumbnail ready: {report.thumbnail_ready_count}")
            print(f"Low resolution: {report.low_resolution_count}")
            print(f"Dark images: {report.dark_image_count}")
            print(f"Text heavy: {report.text_heavy_count}")
            print(f"Average quality score: {report.average_quality_score:.2f}")
            for recommendation in report.recommendations:
                print(f"- {recommendation}")
        else:
            print_json(report.to_dict())
        return 0

    if args.command == "alerts":
        from shopee_agent.alerts import create_alerts_engine
        engine = create_alerts_engine()
        if args.alerts_action == "history":
            alerts_hist = engine.get_history(limit=args.limit)
            if not alerts_hist:
                print("No alerts in history")
                return 0
            for alert in alerts_hist:
                if args.rule and alert["rule"] != args.rule:
                    continue
                if args.severity and alert["severity"] != args.severity:
                    continue
                print(f"[{alert['timestamp']}] {alert['severity']:8} | {alert['rule']:20} | {alert['title']}")
            return 0
        else:
            print("Use: laura alerts history [--limit N] [--rule RULE] [--severity SEVERITY]")
            return 0

    if args.command == "perf-benchmark":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if args.dry_run:
            print("DRY RUN: perf-benchmark simulate")
            samples = [round(0.05 + 0.01 * i, 3) for i in range(args.iterations * args.concurrency)]
            print(json.dumps({"samples": samples, "count": len(samples)}))
            return 0
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1

        def worker_task(worker_id: int) -> list[float]:
            latencies: list[float] = []
            for i in range(args.iterations):
                start = time.time()
                try:
                    if args.endpoint == "product-list":
                        _ = client.get_item_list(access_token=effective_access_token, shop_id=effective_shop_id, offset=0, page_size=args.page_size)
                    else:
                        now = int(time.time())
                        _ = client.get_order_list(access_token=effective_access_token, shop_id=effective_shop_id, time_from=now - 3600, time_to=now, page_size=args.page_size)
                    elapsed = time.time() - start
                    latencies.append(elapsed)
                except Exception:
                    elapsed = time.time() - start
                    latencies.append(elapsed)
            return latencies

        all_latencies: list[float] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futures = [ex.submit(worker_task, wid) for wid in range(args.concurrency)]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    all_latencies.extend(fut.result())
                except Exception:
                    pass
        if not all_latencies:
            print("No samples collected", file=sys.stderr); return 1
        report = {"endpoint": args.endpoint, "samples": len(all_latencies), "p50_s": _statistics.median(all_latencies), "p95_s": sorted(all_latencies)[max(0, int(len(all_latencies)*0.95)-1)], "min_s": min(all_latencies), "max_s": max(all_latencies)}
        print_json(report)
        return 0

    return 2


# --- Shared helpers (re-exported from _utils where possible, or duplicated if specific) ---


def _order_sn_from_payload(payload: dict[str, Any]) -> str:
    for key in ("order_sn", "ordersn", "orderSn", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _find_revenue_candidate(payload: Any) -> float | None:
    preferred_keys = ("buyer_total_amount", "total_amount", "paid_amount", "payment_amount", "order_total", "order_amount", "total_price", "total_item_amount", "grand_total", "amount")
    blocked_keys = ("shipping", "refund", "discount", "voucher", "coupon", "fee", "tax")
    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                candidate = coerce_positive_float(payload.get(key))
                if candidate is not None:
                    return candidate
        for key, value in payload.items():
            key_lower = str(key).lower()
            if any(block in key_lower for block in blocked_keys):
                continue
            candidate = _find_revenue_candidate(value)
            if candidate is not None:
                return candidate
    elif isinstance(payload, list):
        for item in payload:
            candidate = _find_revenue_candidate(item)
            if candidate is not None:
                return candidate
    return None


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


def _build_stock_monitor_report(client, *, access_token: str, shop_id: int, low_stock_threshold: int, max_items: int = 50, page_size: int = 50) -> dict[str, Any]:
    items_seen = 0
    low_stock_items: list[dict[str, Any]] = []
    sample_items: list[dict[str, Any]] = []
    cursor = 0
    while items_seen < max_items:
        resp = client.get_item_list(access_token=access_token, shop_id=shop_id, offset=cursor, page_size=page_size)
        body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
        items = body.get("item", []) if isinstance(body, dict) else []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            items_seen += 1
            if items_seen > max_items:
                break
            item_id = item.get("item_id") or item.get("id")
            item_name = item.get("item_name") or item.get("name") or f"item-{item_id}"
            stock_value = None
            source = "list"
            try:
                if item_id is not None:
                    resp_detail = client.get_item_detail(access_token=access_token, shop_id=shop_id, item_id=int(item_id))
                    detail_body = resp_detail.data.get("response", {}) if isinstance(resp_detail.data, dict) else {}
                    if isinstance(detail_body, dict):
                        variations = detail_body.get("variation_list") or detail_body.get("model_list") or detail_body.get("variations") or []
                        variation_stocks: list[int] = []
                        if isinstance(variations, list):
                            for variation in variations:
                                stock_candidate = _find_stock_candidate(variation)
                                if stock_candidate is not None:
                                    variation_stocks.append(stock_candidate)
                        if variation_stocks:
                            stock_value = sum(variation_stocks)
                            source = "variations"
                        else:
                            stock_value = _find_stock_candidate(detail_body)
                            source = "detail"
            except Exception:
                stock_value = _find_stock_candidate(item)
                source = "list"
            if stock_value is None:
                continue
            record = {"item_id": item_id, "item_name": item_name, "stock": stock_value, "threshold": low_stock_threshold, "source": source}
            if len(sample_items) < 10:
                sample_items.append(record)
            if stock_value <= low_stock_threshold:
                low_stock_items.append(record)
        cursor += page_size
        if not body.get("has_next_page"):
            break
    return {"generated_at": datetime.now(UTC).isoformat(), "shop_id": shop_id, "items_seen": items_seen, "low_stock_threshold": low_stock_threshold, "low_stock_items": low_stock_items, "low_stock_count": len(low_stock_items), "sample_items": sample_items, "inventory_ok": True}
