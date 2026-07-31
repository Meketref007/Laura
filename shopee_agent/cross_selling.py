"""Cross-selling module — recommends complementary products based on order history."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from shopee_agent.paths import REPORTS_DIR
from shopee_agent.skills.registry import Skill, default_registry

CROSS_SELL_GRAPH = REPORTS_DIR / "cross_sell_graph.json"
ORDER_HISTORY_CACHE = REPORTS_DIR / "order_history_cache.jsonl"
PRODUCT_CATALOG_PATH = REPORTS_DIR / "product_catalog.jsonl"


class CrossSellingEngine:
    def __init__(
        self,
        client=None,
        access_token: str | None = None,
        shop_id: int | None = None,
        data_dir: str = "reports",
    ):
        self._client = client
        self._access_token = access_token
        self._shop_id = shop_id
        self._data_dir = Path(data_dir)
        self._orders: list[dict] = []
        self._graph: dict[str, dict[str, int]] = {}

    def load_order_history(self, limit: int = 1000) -> list[dict]:
        orders: list[dict] = []
        if self._client and self._access_token and self._shop_id:
            try:
                now = int(time.time())
                time_from = now - 90 * 86400
                cursor = ""
                page_size = min(limit, 100)
                while len(orders) < limit:
                    resp = self._client.get_order_list(
                        access_token=self._access_token,
                        shop_id=self._shop_id,
                        time_from=time_from,
                        time_to=now,
                        page_size=page_size,
                        cursor=cursor,
                    )
                    data = resp.data
                    order_list = (
                        data.get("response", {}).get("order_list", [])
                        or data.get("data", {}).get("order_list", [])
                    )
                    if not order_list:
                        break
                    for order in order_list:
                        if len(orders) >= limit:
                            break
                        orders.append(order)
                    cursor = (
                        data.get("response", {}).get("next_cursor", "")
                        or data.get("data", {}).get("next_cursor", "")
                    )
                    if not cursor:
                        break
            except Exception:
                pass
        if not orders:
            orders = self._load_cached_orders(limit)
        if orders:
            self._cache_orders(orders)
        self._orders = orders
        self._graph = self.build_product_graph()
        return orders

    def _load_cached_orders(self, limit: int = 1000) -> list[dict]:
        if not ORDER_HISTORY_CACHE.exists():
            return []
        orders: list[dict] = []
        with open(ORDER_HISTORY_CACHE, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    orders.append(json.loads(stripped))
                    if len(orders) >= limit:
                        break
        return orders

    def _cache_orders(self, orders: list[dict]) -> None:
        ORDER_HISTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(ORDER_HISTORY_CACHE, "w", encoding="utf-8") as f:
            for order in orders:
                f.write(json.dumps(order, ensure_ascii=False) + "\n")

    def _extract_item_ids(self, order: dict) -> list[str]:
        items = order.get("item_list", []) or order.get("items", [])
        pids: list[str] = []
        for item in items:
            pid = item.get("item_id", item.get("itemId", ""))
            if pid:
                pids.append(str(pid))
        return list(dict.fromkeys(pids))

    def build_product_graph(self) -> dict:
        graph: defaultdict[str, defaultdict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for order in self._orders:
            pids = self._extract_item_ids(order)
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a, b = pids[i], pids[j]
                    graph[a][b] += 1
                    graph[b][a] += 1
        result = {k: dict(v) for k, v in graph.items()}
        self._persist_graph(result)
        return result

    def _persist_graph(self, graph: dict) -> None:
        CROSS_SELL_GRAPH.parent.mkdir(parents=True, exist_ok=True)
        with open(CROSS_SELL_GRAPH, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)

    def _load_graph(self) -> dict:
        if CROSS_SELL_GRAPH.exists():
            try:
                with open(CROSS_SELL_GRAPH, encoding="utf-8") as f:
                    self._graph = json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupt/empty file (e.g. concurrent writer): treat as empty.
                self._graph = {}
        return self._graph

    def get_recommendations(self, product_id: str, top_n: int = 5) -> list[dict]:
        if not self._graph:
            self._load_graph()
        related = self._graph.get(product_id, {})
        sorted_related = sorted(related.items(), key=lambda x: -x[1])
        results: list[dict] = []
        for pid, count in sorted_related[:top_n]:
            results.append(
                {
                    "product_id": pid,
                    "co_occurrence_count": count,
                    "affinity_score": self.calculate_affinity(product_id, pid),
                }
            )
        return results

    def get_bundle_recommendations(
        self, cart_items: list[str], top_n: int = 3
    ) -> list[dict]:
        if not self._graph:
            self._load_graph()
        scores: defaultdict[str, int] = defaultdict(int)
        for pid in cart_items:
            related = self._graph.get(pid, {})
            for related_id, count in related.items():
                if related_id not in cart_items:
                    scores[related_id] += count
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        results: list[dict] = []
        for pid, score in sorted_scores[:top_n]:
            results.append(
                {
                    "product_id": pid,
                    "bundle_score": score,
                    "affinity_score": (
                        max(
                            self.calculate_affinity(pid, ci) for ci in cart_items
                        )
                        if cart_items
                        else 0
                    ),
                }
            )
        return results

    def get_category_cross_sell(
        self, category_id: int, top_n: int = 5
    ) -> list[dict]:
        catalog = self._load_product_catalog()
        same_category = [
            p for p in catalog if p.get("category_id") == category_id
        ]
        top_products = sorted(
            same_category, key=lambda x: -x.get("sales_count", 0)
        )[:top_n]
        results: list[dict] = []
        for p in top_products:
            results.append(
                {
                    "product_id": str(p.get("item_id", "")),
                    "name": p.get("name", ""),
                    "sales_count": p.get("sales_count", 0),
                    "category_id": category_id,
                }
            )
        return results

    def _load_product_catalog(self) -> list[dict]:
        if not PRODUCT_CATALOG_PATH.exists():
            return []
        products: list[dict] = []
        with open(PRODUCT_CATALOG_PATH, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    products.append(json.loads(stripped))
        return products

    def calculate_affinity(self, product_a: str, product_b: str) -> float:
        if not self._graph:
            self._load_graph()
        if product_a == product_b:
            return 1.0
        related = self._graph.get(product_a, {})
        count = related.get(product_b, 0)
        if count == 0:
            return 0.0
        total = sum(related.values()) or 1
        return round(count / total, 4)

    def get_top_selling_pairs(self, top_n: int = 10) -> list[dict]:
        if not self._graph:
            self._load_graph()
        pairs: dict[tuple[str, str], int] = {}
        seen: set[tuple[str, str]] = set()
        for pid, related in self._graph.items():
            for rid, count in related.items():
                key = tuple(sorted((pid, rid)))
                if key not in seen:
                    seen.add(key)
                    pairs[key] = count
        sorted_pairs = sorted(pairs.items(), key=lambda x: -x[1])[:top_n]
        results: list[dict] = []
        for (a, b), count in sorted_pairs:
            results.append(
                {
                    "product_a": a,
                    "product_b": b,
                    "co_occurrence_count": count,
                    "affinity_score": self.calculate_affinity(a, b),
                }
            )
        return results


class CrossSellingSkill(Skill):
    name = "cross_selling_skill"
    risk_level = "LOW"
    preconditions = {"order_history_available": True}
    effects = {"cross_sell_generated": True}
    cost = 1.5
    priority = 2

    def __init__(self, client=None, **kwargs):
        super().__init__(**kwargs)
        self._client = client

    def run(self, params: dict | None = None, **kwargs) -> dict:
        p = params or kwargs
        access_token = p.get("access_token", "")
        shop_id = p.get("shop_id", 0)
        product_id = p.get("product_id", "")
        category_id = p.get("category_id", 0)
        cart_items = p.get("cart_items", [])
        top_n = p.get("top_n", 5)
        limit = p.get("limit", 1000)
        action = p.get("action", "recommend")

        engine = CrossSellingEngine(
            client=self._client,
            access_token=access_token if access_token else None,
            shop_id=shop_id if shop_id else None,
        )
        engine.load_order_history(limit=limit)

        if not engine._orders:
            return {"error": "No order history available", "orders_loaded": 0}

        result: dict[str, Any] = {
            "orders_loaded": len(engine._orders),
            "action": action,
        }

        if action == "recommend" and product_id:
            result["recommendations"] = engine.get_recommendations(
                product_id, top_n=top_n
            )
        elif action == "bundle" and cart_items:
            result["bundle_recommendations"] = engine.get_bundle_recommendations(
                cart_items, top_n=min(top_n, 3)
            )
        elif action == "category" and category_id:
            result["category_recommendations"] = engine.get_category_cross_sell(
                category_id, top_n=top_n
            )
        elif action == "top_pairs":
            result["top_pairs"] = engine.get_top_selling_pairs(top_n=top_n)
        elif action == "all":
            if product_id:
                result["recommendations"] = engine.get_recommendations(
                    product_id, top_n=top_n
                )
            if cart_items:
                result["bundle_recommendations"] = (
                    engine.get_bundle_recommendations(
                        cart_items, top_n=min(top_n, 3)
                    )
                )
            if category_id:
                result["category_recommendations"] = (
                    engine.get_category_cross_sell(category_id, top_n=top_n)
                )
            result["top_pairs"] = engine.get_top_selling_pairs(top_n=top_n)
        else:
            if product_id:
                result["recommendations"] = engine.get_recommendations(
                    product_id, top_n=top_n
                )
            result["top_pairs"] = engine.get_top_selling_pairs(top_n=top_n)

        result["graph_stats"] = {
            "products_in_graph": len(engine._graph),
        }

        safe_action = action or "recommend"
        tag = product_id or str(category_id) or "all"
        out_path = (
            REPORTS_DIR / f"cross_sell_{safe_action}_{tag}.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        result["output_file"] = str(out_path)
        return result


default_registry.register(CrossSellingSkill)
