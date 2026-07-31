"""Report & Commercial commands: report-sales, report-generate, commercial-control-center."""
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shopee_agent.logger import info, log_error

from ._utils import (
    append_audit_line,
    coerce_positive_float,
    coerce_positive_int,
    ensure_no_api_error,
    first_present_text,
    load_json_file,
    print_json,
)


def register_subparsers(sub):
    report_sales = sub.add_parser("report-sales", help="Gera relatório de vendas (usa /api/v2/order/get_order_list)")
    report_sales.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    report_sales.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    report_sales.add_argument("--days", type=int, default=1, help="Janela de dias para o relatório (default: 1)")
    report_sales.add_argument("--page-size", type=int, default=50, help="Page size para consulta")
    report_sales.add_argument("--dry-run", action="store_true", help="Não chama a API; apenas mostra parâmetros")
    report_generate = sub.add_parser("report-generate", help="Gera resumo diário em Excel e PDF (opcional: resumo LLM)")
    report_generate.add_argument("--inputs", default=None, help="Caminho para inputs JSON (default: reports/laura_profitability_inputs_latest.json)")
    report_generate.add_argument("--out-xlsx", default=None, help="Caminho do arquivo XLSX de saída")
    report_generate.add_argument("--out-pdf", default=None, help="Caminho do arquivo PDF de saída")
    report_generate.add_argument("--no-llm", action="store_true", help="Desativa resumo via LLM (anthropic)")
    commercial_control_center = sub.add_parser("commercial-control-center", help="Gera um snapshot ERP e decide a estratégia comercial automática da loja")
    commercial_control_center.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    commercial_control_center.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    commercial_control_center.add_argument("--days", type=int, default=30, help="Janela de dias para receita/profitabilidade")
    commercial_control_center.add_argument("--low-stock-threshold", type=int, default=5, help="Limite de estoque para o snapshot ERP")
    commercial_control_center.add_argument("--low-margin-threshold", type=float, default=0.20, help="Margem minima para o snapshot ERP")
    commercial_control_center.add_argument("--target-margin-floor", type=float, default=0.25, help="Margem alvo usada para sugerir preco minimo")
    commercial_control_center.add_argument("--max-items", type=int, default=200, help="Limite de itens analisados no catálogo")
    commercial_control_center.add_argument("--page-size", type=int, default=50, help="Tamanho da pagina do catálogo")
    commercial_control_center.add_argument("--erp-output", default="reports/laura_erp_state_latest.json", help="Arquivo JSON da visão ERP")
    commercial_control_center.add_argument("--strategy-output", default="reports/laura_commercial_strategy_latest.json", help="Arquivo JSON da estratégia comercial")
    commercial_control_center.add_argument("--dry-run", action="store_true", help="Não cria caso nem notifica Telegram; apenas gera os relatórios")


def run(args, client=None, cfg=None):
    from shopee_agent.config import ConfigError, load_config
    if cfg is None:
        try:
            cfg = load_config()
        except ConfigError as exc:
            log_error("Config load failed", error=str(exc))
            print(str(exc), file=sys.stderr)
            return 1
    if client is None and args.command not in ("report-generate",):
        from shopee_agent.client import ShopeeClient
        client = ShopeeClient(cfg)

    if args.command == "report-sales":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if args.dry_run:
            now = datetime.now(UTC)
            time_to = int(now.timestamp())
            time_from = int((now - timedelta(days=args.days)).timestamp())
            print("DRY RUN: would fetch orders with parameters:")
            print_json({"shop_id": effective_shop_id, "time_from": time_from, "time_to": time_to, "page_size": args.page_size})
            return 0
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        now = datetime.now(UTC)
        time_to = int(now.timestamp())
        time_from = int((now - timedelta(days=args.days)).timestamp())
        all_orders: list[dict[str, Any]] = []
        cursor = ""
        while True:
            resp = client.get_order_list(access_token=effective_access_token, shop_id=effective_shop_id, time_from=time_from, time_to=time_to, time_range_field="create_time", page_size=args.page_size, cursor=cursor)
            err = ensure_no_api_error(resp.data, "report-sales")
            if err:
                print(err, file=sys.stderr); return 1
            body = resp.data.get("response") if isinstance(resp.data, dict) else None
            if body is None:
                break
            orders = body.get("order_list") or []
            all_orders.extend(orders)
            cursor = body.get("next_cursor", "") or ""
            if not cursor:
                break
        report = {"generated_at": datetime.now(UTC).isoformat(), "shop_id": effective_shop_id, "days": args.days, "orders_count": len(all_orders), "orders": all_orders}
        out_path = Path(f"reports/sales_report_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote report to {out_path}")
        print_json(report)
        return 0

    if args.command == "report-generate":
        from shopee_agent.reporting import generate_daily_reports
        res = generate_daily_reports(inputs_path=args.inputs, out_xlsx=args.out_xlsx, out_pdf=args.out_pdf, use_llm=(not getattr(args, "no_llm", False)))
        print_json(res)
        return 0

    if args.command == "commercial-control-center":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        if args.days < 1:
            print("--days must be >= 1", file=sys.stderr); return 1
        if args.low_stock_threshold < 0:
            print("--low-stock-threshold must be >= 0", file=sys.stderr); return 1
        if args.low_margin_threshold < 0 or args.low_margin_threshold >= 1:
            print("--low-margin-threshold must be between 0 and 1", file=sys.stderr); return 1
        if args.target_margin_floor <= 0 or args.target_margin_floor >= 1:
            print("--target-margin-floor must be between 0 and 1", file=sys.stderr); return 1
        if args.max_items < 1:
            print("--max-items must be >= 1", file=sys.stderr); return 1
        if args.page_size < 1 or args.page_size > 100:
            print("--page-size deve estar entre 1 e 100", file=sys.stderr); return 1
        snapshot = _build_erp_snapshot(client, access_token=effective_access_token, shop_id=effective_shop_id, days=args.days, low_stock_threshold=args.low_stock_threshold, low_margin_threshold=args.low_margin_threshold, target_margin_floor=args.target_margin_floor, max_items=args.max_items, page_size=args.page_size)
        strategy = _decide_commercial_strategy(snapshot)
        erp_state = _build_erp_state(snapshot, strategy)
        erp_output = Path(args.erp_output)
        strategy_output = Path(args.strategy_output)
        erp_state_output = Path("reports/laura_erp_state_latest.json")
        erp_output.parent.mkdir(parents=True, exist_ok=True)
        strategy_output.parent.mkdir(parents=True, exist_ok=True)
        erp_output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        strategy_output.write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
        _persist_erp_state(erp_state, reports_dir=erp_state_output.parent)
        append_audit_line(Path("reports/laura_commercial_strategy_history.jsonl"), {"timestamp": datetime.now(UTC).isoformat(), "action": "commercial_control_center", "shop_id": effective_shop_id, "erp_output": str(erp_output), "strategy_output": str(strategy_output), "primary_action_key": strategy.get("primary_action_key"), "commercial_mode": strategy.get("commercial_mode"), "erp_score": erp_state.get("erp_score")})
        response: dict[str, Any] = {"status": "ok", "erp_output": str(erp_output), "strategy_output": str(strategy_output), "erp_state_output": str(erp_state_output), "erp_score": erp_state.get("erp_score"), "erp_status": erp_state.get("erp_status"), "commercial_mode": strategy.get("commercial_mode"), "primary_action_key": strategy.get("primary_action_key"), "primary_reason": strategy.get("primary_reason"), "objectives": strategy.get("objectives", []), "risks": strategy.get("risks", []), "supported_for_approval": strategy.get("supported_for_approval")}
        if args.dry_run or not strategy.get("supported_for_approval"):
            response["created_case"] = None
            response["telegram_notified"] = False
            response["next_actions"] = erp_state.get("next_actions", [])
            print_json(response)
            return 0
        case = _create_commercial_remediation_case(strategy, snapshot, reports_dir=erp_state_output.parent)
        if case is None:
            response["created_case"] = None
            response["telegram_notified"] = False
            response["next_actions"] = erp_state.get("next_actions", [])
            print_json(response)
            return 0
        notified = _send_telegram_commercial_case(case, strategy, reports_dir=erp_state_output.parent)
        response["created_case"] = case.get("case_id")
        response["telegram_notified"] = notified
        response["case_action_key"] = case.get("action_key")
        response["targets_count"] = len(case.get("payload", []) or [])
        response["next_actions"] = erp_state.get("next_actions", [])
        print_json(response)
        return 0

    return 2


# --- ERP Snapshot helpers ---
def _ingest_order_revenue_report(client, *, access_token: str, shop_id: int, days: int, page_size: int = 50, max_orders: int = 200) -> dict[str, Any]:
    now = datetime.now(UTC)
    time_to = int(now.timestamp())
    time_from = int((now - timedelta(days=days)).timestamp())
    max_window_seconds = 15 * 24 * 3600
    orders_seen = 0
    paid_orders = 0
    revenue_total = 0.0
    total_cogs = 0.0
    sample_orders: list[dict[str, Any]] = []
    window_start = time_from
    while window_start < time_to and orders_seen < max_orders:
        window_end = min(window_start + max_window_seconds, time_to)
        cursor = ""
        while orders_seen < max_orders:
            resp = client.get_order_list(access_token=access_token, shop_id=shop_id, time_from=window_start, time_to=window_end, time_range_field="update_time", order_status="COMPLETED", page_size=page_size, cursor=cursor)
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            orders = body.get("order_list", []) if isinstance(body, dict) else []
            info(f"[ingest_order_revenue] API returned {len(orders)} orders in window {window_start}->{window_end} (total seen: {orders_seen})")
            if not orders:
                break
            for order in orders:
                if not isinstance(order, dict):
                    continue
                orders_seen += 1
                if orders_seen > max_orders:
                    break
                order_sn = _order_sn_from_payload(order)
                detail_payload: dict[str, Any] | None = None
                amount = _find_revenue_candidate(order)
                if amount is None and order_sn:
                    try:
                        detail_resp = client.get_order_detail(access_token=access_token, shop_id=shop_id, order_sn=order_sn)
                        detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
                        if isinstance(detail_body, dict):
                            detail_payload = detail_body
                            amount = _find_revenue_candidate(detail_body)
                    except Exception:
                        detail_payload = None
                escrow_amount = None
                if order_sn:
                    try:
                        escrow_resp = client.get_escrow_detail(access_token=access_token, shop_id=shop_id, order_sn=order_sn)
                        escrow_body = escrow_resp.data.get("response", {}) if isinstance(escrow_resp.data, dict) else {}
                        if isinstance(escrow_body, dict):
                            escrow_amount = _find_revenue_candidate(escrow_body)
                    except Exception:
                        escrow_amount = None
                if escrow_amount is not None:
                    amount = escrow_amount
                if amount is None:
                    continue
                order_cogs = 0.0
                items = []
                if isinstance(detail_payload, dict):
                    items = _extract_order_items(detail_payload)
                if not items:
                    items = _extract_order_items(order)
                if not items and order_sn:
                    try:
                        detail_resp = client.get_order_detail(access_token=access_token, shop_id=shop_id, order_sn=order_sn)
                        detail_body = detail_resp.data.get("response", {}) if isinstance(detail_resp.data, dict) else {}
                        if isinstance(detail_body, dict):
                            detail_payload = detail_body
                            items = _extract_order_items(detail_body)
                    except Exception:
                        detail_payload = detail_payload if isinstance(detail_payload, dict) else None
                for it in items:
                    iid = it.get("item_id") or ""
                    qty = int(it.get("quantity") or 1)
                    cost = _get_cost_for_item(str(iid)) if iid else None
                    if cost is None:
                        continue
                    order_cogs += float(cost) * qty
                paid_orders += 1
                revenue_total += amount
                total_cogs += order_cogs
                if len(sample_orders) < 10:
                    sample_orders.append({"order_sn": order_sn, "amount": round(amount, 2), "source": "detail" if detail_payload else "list"})
            cursor = str(body.get("next_cursor", "") or "") if isinstance(body, dict) else ""
            if not cursor:
                break
        window_start = window_end
    event = {"timestamp": now.isoformat(), "source": "ingest_order_revenue", "window_days": days, "shop_id": shop_id, "orders_seen": orders_seen, "paid_orders": paid_orders, "revenue": round(revenue_total, 2), "cogs": round(total_cogs, 2), "ad_spend": 0.0, "shipping_subsidy": 0.0, "refunds": 0.0, "orders": paid_orders, "sample_orders": sample_orders}
    info(f"[ingest_order_revenue] Final: {paid_orders} paid orders, revenue={revenue_total:.2f} BRL, sample_count={len(sample_orders)}")
    return event


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


def _extract_order_items(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    def visit(obj: Any):
        if isinstance(obj, dict):
            for k in ("order_items", "items", "item_list", "order_item_list"):
                if k in obj and isinstance(obj[k], list):
                    for it in obj[k]:
                        if isinstance(it, dict):
                            iid = it.get("item_id") or it.get("itemid") or it.get("itemId") or it.get("sku")
                            vid = it.get("variation_id") or it.get("variationid") or it.get("variationId")
                            qty = it.get("quantity") or it.get("qty") or it.get("item_quantity") or it.get("normal_stock")
                            try:
                                q = int(qty) if qty is not None else 1
                            except Exception:
                                q = 1
                            candidates.append({"item_id": str(iid) if iid is not None else "", "variation_id": vid, "quantity": q})
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for it in obj:
                visit(it)
    visit(payload)
    return candidates


def _get_cost_for_item(item_id: str) -> float | None:
    _PRODUCT_COSTS_PATH = Path("reports/product_costs.json")
    try:
        if not _PRODUCT_COSTS_PATH.exists():
            return None
        data = json.loads(_PRODUCT_COSTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return float(data.get(str(item_id))) if str(item_id) in data else None
    except Exception:
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
    return {"generated_at": datetime.now(UTC).isoformat(), "shop_id": shop_id, "low_margin_threshold": low_margin_threshold, "target_margin_floor": target_margin_floor, "items_seen": items_seen, "reviewed_count": len(reviewed_entries), "ok_count": sum(1 for entry in reviewed_entries if entry.get("status") == "ok"), "low_margin_count": len(low_margin_entries), "missing_cost_count": len(missing_cost_entries), "missing_price_count": len(missing_price_entries), "top_risks": sorted([entry for entry in low_margin_entries if entry.get("margin_pct") is not None], key=lambda entry: entry.get("margin_pct", 0.0))[:20], "reviewed_entries": reviewed_entries, "low_margin_entries": low_margin_entries, "missing_cost_entries": missing_cost_entries, "missing_price_entries": missing_price_entries}


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


def _build_erp_snapshot(client, *, access_token: str, shop_id: int, days: int, low_stock_threshold: int, low_margin_threshold: float, target_margin_floor: float, max_items: int, page_size: int) -> dict[str, Any]:
    profitability = _ingest_order_revenue_report(client, access_token=access_token, shop_id=shop_id, days=days, page_size=page_size, max_orders=200)
    inventory = _build_stock_monitor_report(client, access_token=access_token, shop_id=shop_id, low_stock_threshold=low_stock_threshold, max_items=max_items, page_size=page_size)
    margin_review = _build_margin_review_report(client, access_token=access_token, shop_id=shop_id, low_margin_threshold=low_margin_threshold, target_margin_floor=target_margin_floor, max_items=max_items, page_size=page_size)
    health = load_json_file("reports/laura_health_latest.json", "health report") or {}
    metrics = profitability if isinstance(profitability, dict) else {}
    profit_metrics = metrics.get("metrics", {}) if isinstance(metrics.get("metrics"), dict) else {}
    snapshot = {"generated_at": datetime.now(UTC).isoformat(), "shop_id": shop_id, "financial": profitability, "inventory": inventory, "margin_review": margin_review, "health": health, "erp_summary": {"orders": profit_metrics.get("orders"), "revenue": profit_metrics.get("revenue"), "profit": profit_metrics.get("profit"), "margin_pct": profit_metrics.get("margin_pct"), "refund_rate_pct": profit_metrics.get("refund_rate_pct"), "low_stock_count": inventory.get("low_stock_count") if isinstance(inventory, dict) else None, "low_margin_count": margin_review.get("low_margin_count") if isinstance(margin_review, dict) else None, "health_status": health.get("overall_status") or health.get("status")}}
    return snapshot


def _decide_commercial_strategy(snapshot: dict[str, Any]) -> dict[str, Any]:
    financial = snapshot.get("financial", {}) if isinstance(snapshot.get("financial"), dict) else {}
    metrics = financial.get("metrics", {}) if isinstance(financial.get("metrics"), dict) else {}
    inventory = snapshot.get("inventory", {}) if isinstance(snapshot.get("inventory"), dict) else {}
    margin_review = snapshot.get("margin_review", {}) if isinstance(snapshot.get("margin_review"), dict) else {}
    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}
    revenue = float(metrics.get("revenue", 0.0) or 0.0)
    profit = float(metrics.get("profit", 0.0) or 0.0)
    margin_pct = float(metrics.get("margin_pct", 0.0) or 0.0)
    refund_rate_pct = float(metrics.get("refund_rate_pct", 0.0) or 0.0)
    roas = metrics.get("roas")
    low_stock_count = int(inventory.get("low_stock_count", 0) or 0)
    low_margin_count = int(margin_review.get("low_margin_count", 0) or 0)
    health_status = str(health.get("overall_status") or health.get("status") or health.get("overallStatus") or "UNKNOWN").upper()
    objectives: list[str] = []
    secondary_actions: list[str] = []
    primary_action = "monitor_only"
    primary_reason = "No commercial breach detected; keep observing."
    commercial_mode = "stabilize"
    if health_status not in {"HEALTHY", "OK", "GOOD"}:
        commercial_mode = "stabilize"
        objectives.append("Restaurar saúde operacional antes de escalar")
        secondary_actions.append("Revisar alertas e latência da API antes de decisões agressivas")
    if low_margin_count > 0 or margin_pct < 20:
        primary_action = "protect_margin"
        commercial_mode = "optimize_margin"
        primary_reason = "Itens com margem baixa identificados; prioridade é proteger margem e elevar preço mínimo."
        objectives.append("Proteger margem")
        secondary_actions.append("Reprecificar SKUs abaixo do piso")
        secondary_actions.append("Revisar custos cadastrados em produtos com margem crítica")
    elif refund_rate_pct >= 5.0 or profit < 0:
        primary_action = "refund_guard"
        commercial_mode = "reduce_loss"
        primary_reason = "Sinais de perdas/reembolsos exigem contenção operacional imediata."
        objectives.append("Reduzir perdas e reembolsos")
        secondary_actions.append("Auditar itens com maior incidência de reembolso")
    elif low_stock_count > 0 and revenue > 0:
        primary_action = "scale_winners"
        commercial_mode = "grow_winners"
        primary_reason = "Há demanda e o estoque ainda permite escalar os produtos com melhor performance."
        objectives.append("Escalar vencedores")
        secondary_actions.append("Reforçar estoque dos itens vencedores")
    elif roas is not None:
        try:
            roas_value = float(roas)
        except Exception:
            roas_value = None
        if roas_value is not None and roas_value < 1.0:
            primary_action = "pause_low_roas_ads"
            commercial_mode = "trim_ads"
            primary_reason = "ROAS baixo detectado; a estratégia prioriza corte de desperdício publicitário."
            objectives.append("Cortar mídia ineficiente")
            secondary_actions.append("Pausar campanhas abaixo do piso de ROAS")
    elif revenue <= 0:
        commercial_mode = "observe"
        primary_reason = "Sem receita detectada; estratégia permanece em observação até o tráfego voltar."
    if not objectives:
        objectives.append("Manter operação estável")
    risks = []
    if low_margin_count > 0:
        risks.append(f"{low_margin_count} item(ns) abaixo do piso de margem")
    if low_stock_count > 0:
        risks.append(f"{low_stock_count} item(ns) com estoque baixo")
    if refund_rate_pct >= 5.0:
        risks.append(f"Refund rate alto: {refund_rate_pct:.2f}%")
    if health_status not in {"HEALTHY", "OK", "GOOD"}:
        risks.append(f"Saúde operacional: {health_status}")
    recommended_actions = [{"action_key": primary_action, "reason": primary_reason, "supported": primary_action in {"protect_margin", "scale_winners", "pause_low_roas_ads", "refund_guard"}}]
    for secondary in secondary_actions:
        recommended_actions.append({"action_key": "recommendation", "reason": secondary, "supported": False})
    return {"generated_at": datetime.now(UTC).isoformat(), "commercial_mode": commercial_mode, "primary_action_key": primary_action, "primary_reason": primary_reason, "objectives": objectives, "risks": risks, "recommended_actions": recommended_actions, "guardrails": {"min_margin_pct": 20.0, "target_margin_floor": margin_review.get("target_margin_floor", 0.25), "low_stock_threshold": inventory.get("low_stock_threshold"), "max_inventory_items": inventory.get("items_seen"), "profit": profit, "revenue": revenue, "margin_pct": margin_pct, "refund_rate_pct": refund_rate_pct, "health_status": health_status}, "supported_for_approval": primary_action in {"protect_margin", "scale_winners", "pause_low_roas_ads", "refund_guard"}}


def _create_commercial_remediation_case(strategy: dict[str, Any], snapshot: dict[str, Any], *, reports_dir: Path) -> dict[str, Any] | None:
    action_key = str(strategy.get("primary_action_key") or "monitor_only")
    if action_key == "monitor_only":
        return None
    payload: list[dict[str, Any]] = []
    if action_key == "protect_margin":
        payload = snapshot.get("margin_review", {}).get("low_margin_entries", []) if isinstance(snapshot.get("margin_review"), dict) else []
    elif action_key == "scale_winners":
        payload = snapshot.get("inventory", {}).get("sample_items", []) if isinstance(snapshot.get("inventory"), dict) else []
    elif action_key == "refund_guard" or action_key == "pause_low_roas_ads":
        payload = snapshot.get("financial", {}).get("sample_orders", []) if isinstance(snapshot.get("financial"), dict) else []
    case = {"case_id": f"{action_key}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}", "action_key": action_key, "title": f"Commercial strategy: {action_key}", "created_at": datetime.now(UTC).isoformat(), "executed": False, "execute_on_approve": True, "payload": payload, "strategy": strategy, "snapshot": {"financial": snapshot.get("financial", {}).get("metrics", {}) if isinstance(snapshot.get("financial"), dict) else {}, "inventory": {"low_stock_count": snapshot.get("inventory", {}).get("low_stock_count") if isinstance(snapshot.get("inventory"), dict) else None}, "margin_review": {"low_margin_count": snapshot.get("margin_review", {}).get("low_margin_count") if isinstance(snapshot.get("margin_review"), dict) else None}}}
    cases_path = reports_dir / "laura_remediation_cases.jsonl"
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    with cases_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {"timestamp": datetime.now(UTC).isoformat(), "action": "create_commercial_remediation_case", "case_id": case["case_id"], "action_key": action_key, "payload_items": len(payload)})
    return case


def _send_telegram_commercial_case(case: dict[str, Any], strategy: dict[str, Any], *, reports_dir: Path) -> bool:
    token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    action_key = str(case.get("action_key", "monitor_only"))
    lines = ["Laura Commercial Control Center", f"Case: {case.get('case_id')}", f"Modo: {strategy.get('commercial_mode')}", f"Ação principal: {action_key}", f"Razão: {strategy.get('primary_reason')}"]
    for item in (case.get("payload", []) or [])[:5]:
        if not isinstance(item, dict):
            continue
        label = item.get("variation_name") or item.get("item_name") or item.get("order_sn") or item.get("item_id") or "item"
        lines.append(f"- {label}")
    keyboard = {"inline_keyboard": [[{"text": "Aprovar", "callback_data": f"approve:{case['case_id']}"}, {"text": "Cancelar", "callback_data": f"cancel:{case['case_id']}"}]]}
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": "\n".join(lines), "reply_markup": json.dumps(keyboard, ensure_ascii=False), "disable_web_page_preview": True}, timeout=10)
        append_audit_line(reports_dir / "laura_remediation_audit.jsonl", {"timestamp": datetime.now(UTC).isoformat(), "action": "notify_commercial_remediation_case", "case_id": case.get("case_id"), "action_key": action_key})
        return True
    except Exception:
        return False


def _build_erp_state(snapshot: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    financial = snapshot.get("financial", {}) if isinstance(snapshot.get("financial"), dict) else {}
    inventory = snapshot.get("inventory", {}) if isinstance(snapshot.get("inventory"), dict) else {}
    margin_review = snapshot.get("margin_review", {}) if isinstance(snapshot.get("margin_review"), dict) else {}
    health = snapshot.get("health", {}) if isinstance(snapshot.get("health"), dict) else {}
    financial_metrics = financial.get("metrics", {}) if isinstance(financial.get("metrics"), dict) else {}
    low_stock_items = inventory.get("low_stock_items", []) if isinstance(inventory.get("low_stock_items"), list) else []
    low_margin_entries = margin_review.get("low_margin_entries", []) if isinstance(margin_review.get("low_margin_entries"), list) else []
    revenue = float(financial_metrics.get("revenue", 0.0) or 0.0)
    profit = float(financial_metrics.get("profit", 0.0) or 0.0)
    margin_pct = float(financial_metrics.get("margin_pct", 0.0) or 0.0)
    refund_rate_pct = float(financial_metrics.get("refund_rate_pct", 0.0) or 0.0)
    low_stock_count = int(inventory.get("low_stock_count", 0) or 0)
    low_margin_count = int(margin_review.get("low_margin_count", 0) or 0)
    health_status = str(health.get("overall_status") or health.get("status") or "UNKNOWN").upper()
    score = 100.0
    if revenue <= 0:
        score -= 35
    if profit <= 0:
        score -= 15
    if margin_pct <= 0:
        score -= 10
    elif margin_pct < 20:
        score -= min(20, (20 - margin_pct) * 1.5)
    if refund_rate_pct >= 5:
        score -= min(20, (refund_rate_pct - 4) * 2)
    score -= min(25, low_stock_count * 2.5)
    score -= min(30, low_margin_count * 4)
    if health_status not in {"HEALTHY", "OK", "GOOD"}:
        score -= 15
    score = max(0.0, min(100.0, score))
    if score >= 80:
        erp_status = "healthy"
    elif score >= 60:
        erp_status = "watch"
    elif score >= 40:
        erp_status = "at_risk"
    else:
        erp_status = "critical"
    modules = {"finance": {"revenue": revenue, "profit": profit, "margin_pct": margin_pct, "refund_rate_pct": refund_rate_pct, "orders": financial_metrics.get("orders", 0)}, "inventory": {"low_stock_count": low_stock_count, "low_stock_threshold": inventory.get("low_stock_threshold"), "tracked_items": inventory.get("items_seen")}, "pricing": {"low_margin_count": low_margin_count, "target_margin_floor": margin_review.get("target_margin_floor", 0.25)}, "health": {"status": health_status, "alerts": len(health.get("alerts", [])) if isinstance(health.get("alerts"), list) else 0}, "automation": {"recommended_primary_action": strategy.get("primary_action_key"), "commercial_mode": strategy.get("commercial_mode"), "supported_for_approval": strategy.get("supported_for_approval")}}
    next_actions: list[dict[str, Any]] = []
    primary_action = str(strategy.get("primary_action_key") or "monitor_only")
    if primary_action != "monitor_only":
        next_actions.append({"action_key": primary_action, "priority": 1, "reason": strategy.get("primary_reason")})
    if low_stock_count > 0:
        next_actions.append({"action_key": "replenish_stock", "priority": 2, "reason": "Estoque baixo detectado no snapshot ERP", "targets": low_stock_items[:10]})
    if low_margin_count > 0:
        next_actions.append({"action_key": "protect_margin", "priority": 2, "reason": "Margem abaixo do piso em itens críticos", "targets": low_margin_entries[:10]})
    if refund_rate_pct >= 5.0:
        next_actions.append({"action_key": "refund_guard", "priority": 2, "reason": "Taxa de reembolso elevada no snapshot ERP"})
    return {"generated_at": datetime.now(UTC).isoformat(), "erp_status": erp_status, "erp_score": round(score, 2), "snapshot": snapshot, "strategy": strategy, "modules": modules, "next_actions": next_actions, "decision_summary": {"primary_action_key": primary_action, "commercial_mode": strategy.get("commercial_mode"), "objective_count": len(strategy.get("objectives", []) if isinstance(strategy.get("objectives"), list) else []), "risk_count": len(strategy.get("risks", []) if isinstance(strategy.get("risks"), list) else [])}}


def _persist_erp_state(state: dict[str, Any], *, reports_dir: Path) -> tuple[Path, Path]:
    latest_path = reports_dir / "laura_erp_state_latest.json"
    history_path = reports_dir / "laura_erp_state_history.jsonl"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False) + "\n")
    return latest_path, history_path
