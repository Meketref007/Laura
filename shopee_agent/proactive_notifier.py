"""Notificacoes proativas - alertas sobre estoque baixo, avaliacoes ruins, cancelamentos."""
import json
from datetime import UTC, datetime

from shopee_agent.paths import PROACTIVE_LAST_RUN, PROACTIVE_STATE, REPORTS_DIR

LAST_RUN_FILE = PROACTIVE_LAST_RUN
STATE_FILE = PROACTIVE_STATE


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"low_stock_items": {}, "bad_ratings_seen": set(), "cancellations_seen": set(), "last_restock_check": 0}


def _save_state(state: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Convert sets to lists for JSON
    s = dict(state)
    s["bad_ratings_seen"] = list(s.get("bad_ratings_seen", set()))
    s["cancellations_seen"] = list(s.get("cancellations_seen", set()))
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def _restore_state(raw: dict) -> dict:
    state = dict(raw)
    state["bad_ratings_seen"] = set(raw.get("bad_ratings_seen", []))
    state["cancellations_seen"] = set(raw.get("cancellations_seen", []))
    return state


def check_low_stock(seller_client, threshold: int = 5) -> list[dict]:
    """Retorna produtos com estoque abaixo do threshold."""
    alerts = []
    try:
        getter = getattr(seller_client, "get_products", None) or getattr(seller_client, "get_item_list", None)
        raw = getter(limit=100)
        for item in raw if isinstance(raw, list) else raw.get("item_list", raw.get("items", [])):
            stock = item.get("stock", 0)
            name = item.get("item_name", item.get("name", "?"))

            # Check variants
            variants = item.get("variations", [])
            for v in variants:
                vstock = v.get("stock", 0)
                if 0 < vstock <= threshold:
                    alerts.append({
                        "type": "low_stock",
                        "item_id": item.get("item_id"),
                        "name": f"{name} - {v.get('name', '')}",
                        "stock": vstock,
                        "threshold": threshold,
                    })

            if 0 < stock <= threshold:
                alerts.append({
                    "type": "low_stock",
                    "item_id": item.get("item_id"),
                    "name": name,
                    "stock": stock,
                    "threshold": threshold,
                })
    except Exception as e:
        print(f"[ProactiveNotifier] low_stock error: {e}")
    return alerts


def check_bad_ratings(seller_client, hours_back: int = 24) -> list[dict]:
    """Retorna avaliacoes ruins (<= 3 estrelas) das ultimas horas."""
    alerts = []
    try:
        ratings = seller_client.get_ratings(limit=50)
        for r in ratings if isinstance(ratings, list) else ratings.get("ratings", []):
            stars = r.get("rating", r.get("star", 0))
            if stars <= 3:
                ctime = r.get("ctime", "")
                alerts.append({
                    "type": "bad_rating",
                    "order_sn": r.get("order_sn", ""),
                    "buyer": r.get("buyer_username", "?"),
                    "stars": stars,
                    "comment": r.get("comment", "")[:200],
                    "time": ctime,
                })
    except Exception as e:
        print(f"[ProactiveNotifier] bad_ratings error: {e}")
    return alerts


def check_cancellations(seller_client, hours_back: int = 24) -> list[dict]:
    """Retorna cancelamentos recentes."""
    alerts = []
    try:
        orders = seller_client.get_orders(limit=100)
        for o in orders if isinstance(orders, list) else orders.get("orders", []):
            status = o.get("order_status", o.get("status", ""))
            if status in ("CANCELLED", "cancelled", "INVOICE_CANCELLED"):
                ctime = o.get("create_time", o.get("ctime", ""))
                alerts.append({
                    "type": "cancellation",
                    "order_sn": o.get("order_sn", ""),
                    "buyer": o.get("buyer_username", "?"),
                    "reason": o.get("cancel_reason", "N/A")[:200],
                    "amount": o.get("total_amount", o.get("escrow_amount", 0)),
                    "time": ctime,
                })
    except Exception as e:
        print(f"[ProactiveNotifier] cancellations error: {e}")
    return alerts


def run_all(seller_client, low_stock_threshold: int = 5, hours_back: int = 24) -> list[dict]:
    """Roda todos os checks e retorna alerts nao vistos."""
    raw = _load_state()
    state = _restore_state(raw)
    now = datetime.now(UTC).isoformat()
    new_alerts = []

    # Low stock
    low = check_low_stock(seller_client, threshold=low_stock_threshold)
    known_low = state.get("low_stock_items", {})
    for a in low:
        key = f"{a['item_id']}_{a['name']}"
        if key not in known_low or known_low[key] != a["stock"]:
            new_alerts.append(a)
            state["low_stock_items"][key] = a["stock"]

    # Bad ratings
    bad = check_bad_ratings(seller_client, hours_back=hours_back)
    for a in bad:
        key = f"{a['order_sn']}_{a['stars']}"
        if key not in state["bad_ratings_seen"]:
            new_alerts.append(a)
            state["bad_ratings_seen"].add(key)

    # Cancellations
    canc = check_cancellations(seller_client, hours_back=hours_back)
    for a in canc:
        key = a["order_sn"]
        if key not in state["cancellations_seen"]:
            new_alerts.append(a)
            state["cancellations_seen"].add(key)

    state["_last_run"] = now
    _save_state(state)
    return new_alerts
