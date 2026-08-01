"""Previsao de estoque - sugere reabastecimento baseado em vendas historicas."""
import json
import os
from pathlib import Path

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
PREDICTION_FILE = REPORTS_DIR / "stock_predictions.json"


def predict_restock(
    seller_client, days_history: int = 30, lead_time_days: int = 7, safety_stock_days: int = 7
) -> list[dict]:
    """Preve quando reabastecer cada SKU baseado em vendas."""
    from collections import Counter

    recommendations = []
    try:
        orders = seller_client.get_orders(limit=200)
        order_list = orders if isinstance(orders, list) else orders.get("orders", [])

        # Contar vendas por item
        sales_count: dict[str, int] = Counter()
        sales_by_item: dict[str, dict] = {}
        for o in order_list:
            items = o.get("item_list", o.get("items", []))
            for it in items:
                iid = str(it.get("item_id", ""))
                qty = it.get("quantity_sold", it.get("variation_quantity_purchased", 1))
                sales_count[iid] += qty
                if iid not in sales_by_item:
                    sales_by_item[iid] = {
                        "name": it.get("item_name", "?"),
                        "price": it.get("item_price", 0),
                    }

        # Obter estoque atual
        products = seller_client.get_products(limit=200)
        for p in products:
            iid = str(p.get("item_id", ""))
            stock = p.get("stock", 0)
            name = p.get("item_name", p.get("name", "?"))
            daily_sales = sales_count.get(iid, 0) / max(days_history, 1)

            if daily_sales <= 0:
                continue

            days_until_empty = stock / daily_sales if daily_sales > 0 else 999
            reorder_point = lead_time_days * daily_sales + safety_stock_days * daily_sales

            if days_until_empty < lead_time_days + safety_stock_days:
                recommendations.append({
                    "item_id": iid,
                    "name": name,
                    "current_stock": stock,
                    "daily_sales": round(daily_sales, 2),
                    "days_until_empty": round(days_until_empty, 1),
                    "reorder_point": round(reorder_point),
                    "suggested_restock": round(reorder_point * 1.5),
                    "priority": "alta" if days_until_empty < lead_time_days else "media",
                })

        recommendations.sort(key=lambda r: r["days_until_empty"])

        # Salvar
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        PREDICTION_FILE.write_text(
            json.dumps(recommendations, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    except Exception as e:
        print(f"[StockPredictor] error: {e}")

    return recommendations
