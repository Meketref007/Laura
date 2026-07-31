"""Order & Ingest commands: order-ship, ingest-order-revenue, approve-remediation."""
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shopee_agent.logger import info, log_error

from ._utils import (
    append_audit_line,
    coerce_positive_float,
    ensure_no_api_error,
    print_json,
)


def register_subparsers(sub):
    order_ship = sub.add_parser("order-ship", help="Marca pedido como enviado (wrapper para /api/v2/logistics/ship_order)")
    order_ship.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    order_ship.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    order_ship.add_argument("--order-sn", default=None, help="Order SN para enviar")
    order_ship.add_argument("--all-pending", action="store_true", help="Enviar todos pedidos PAID pendientes")
    ingest_order_revenue = sub.add_parser("ingest-order-revenue", help="Ingesta receita dos pedidos pagos e grava em profitability_events.jsonl")
    ingest_order_revenue.add_argument("--access-token", default=None, help="Access token; default do .env se omitido")
    ingest_order_revenue.add_argument("--shop-id", type=int, default=None, help="Shop ID; default do .env se omitido")
    ingest_order_revenue.add_argument("--days", type=int, default=30, help="Janela de dias para ingestao (default: 30)")
    ingest_order_revenue.add_argument("--page-size", type=int, default=50, help="Page size para consulta de pedidos")
    ingest_order_revenue.add_argument("--max-orders", type=int, default=200, help="Limite de pedidos a processar na execucao")
    ingest_order_revenue.add_argument("--dry-run", action="store_true", help="Não chama a API; apenas mostra o resumo previsto")
    approve_remediation = sub.add_parser("approve-remediation", help="Aprova um caso de remediação gerado por Laura (marca executed=true)")
    approve_remediation.add_argument("case_id", help="ID do caso a aprovar")


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

    if args.command == "order-ship":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if not effective_access_token:
            print("Missing access token", file=sys.stderr); return 1
        if effective_shop_id is None:
            print("Missing shop id", file=sys.stderr); return 1
        results: list[dict[str, Any]] = []
        if args.all_pending:
            now = int(time.time())
            time_from = int((datetime.now(UTC) - timedelta(days=7)).timestamp())
            resp = client.get_order_list(access_token=effective_access_token, shop_id=effective_shop_id, time_from=time_from, time_to=now, page_size=100)
            err = ensure_no_api_error(resp.data, "order-ship")
            if err:
                print(err, file=sys.stderr); return 1
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            orders = body.get("order_list", []) if isinstance(body, dict) else []
            for order in orders:
                if not isinstance(order, dict):
                    continue
                status = str(order.get("order_status") or "").upper()
                if status != "PAID":
                    continue
                order_sn = str(order.get("order_sn") or "").strip()
                if not order_sn:
                    continue
                try:
                    ship_resp = client.ship_order(access_token=effective_access_token, shop_id=effective_shop_id, order_sn=order_sn)
                    results.append({"order_sn": order_sn, "response": ship_resp.data})
                except Exception as exc:
                    results.append({"order_sn": order_sn, "error": str(exc)})
        else:
            if not args.order_sn:
                print("Provide --order-sn or --all-pending", file=sys.stderr); return 1
            try:
                ship_resp = client.ship_order(access_token=effective_access_token, shop_id=effective_shop_id, order_sn=args.order_sn)
                results.append({"order_sn": args.order_sn, "response": ship_resp.data})
            except Exception as exc:
                results.append({"order_sn": args.order_sn, "error": str(exc)})
        print_json({"results": results})
        return 0

    if args.command == "ingest-order-revenue":
        effective_access_token = args.access_token or cfg.default_access_token
        effective_shop_id = args.shop_id if args.shop_id is not None else cfg.default_shop_id
        if effective_access_token is None or effective_shop_id is None:
            print("--access-token and --shop-id devem ser fornecidos ou configurados no .env", file=sys.stderr); return 1
        if args.dry_run:
            preview = {"shop_id": effective_shop_id, "days": args.days, "page_size": args.page_size, "max_orders": args.max_orders, "output": "reports/laura_profitability_events.jsonl"}
            print("DRY RUN: ingest-order-revenue preview:")
            print_json(preview)
            return 0
        try:
            event = _ingest_order_revenue_report(client, access_token=effective_access_token, shop_id=effective_shop_id, days=args.days, page_size=args.page_size, max_orders=args.max_orders)
        except Exception as exc:
            print(f"Failed to ingest order revenue: {exc}", file=sys.stderr); return 1
        events_path = Path("reports/laura_profitability_events.jsonl")
        append_audit_line(events_path, event)
        summary = {"generated_at": event["timestamp"], "events_file": str(events_path), "orders_seen": event["orders_seen"], "paid_orders": event["paid_orders"], "revenue": event["revenue"], "window_days": event["window_days"]}
        print_json(summary)
        return 0

    if args.command == "approve-remediation":
        case_id = args.case_id
        history_file = Path("reports/laura_remediation_cases.jsonl")
        if not history_file.exists():
            print(f"Remediation history not found: {history_file}", file=sys.stderr); return 1
        updated = False
        try:
            lines = history_file.read_text(encoding="utf-8").splitlines()
            new_lines = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    new_lines.append(line)
                    continue
                if obj.get("case_id") == case_id:
                    if obj.get("executed"):
                        print(f"Case {case_id} already executed")
                        return 0
                    obj["executed"] = True
                    obj["executed_at"] = datetime.now(UTC).isoformat()
                    obj["result"] = f"Approved via CLI ({os.getenv('USER','cli')})"
                    updated = True
                new_lines.append(json.dumps(obj, ensure_ascii=False))
            if not updated:
                print(f"Case not found: {case_id}", file=sys.stderr); return 1
            history_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            audit_path = Path("reports/laura_remediation_audit.jsonl")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            append_audit_line(audit_path, {"timestamp": datetime.now(UTC).isoformat(), "action": "approve_remediation", "case_id": case_id, "approved_by": os.getenv('USER','cli')})
            print(f"Approved remediation case: {case_id}")
            return 0
        except Exception as exc:
            print(f"Failed to approve remediation: {exc}", file=sys.stderr); return 1

    return 2


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
                    cost = None
                    if iid:
                        cost = _get_cost_for_item(str(iid))
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
