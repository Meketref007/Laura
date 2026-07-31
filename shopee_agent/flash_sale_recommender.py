"""
flash_sale_recommender.py - Fase 33

Identifica produtos com estoque alto e sem vendas recentes para sugerir
flash sales automáticas com custo zero.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .client import ShopeeClient
from .logger import warning


@dataclass
class FlashSaleCandidate:
    item_id: int
    item_name: str
    stock: int
    sales_7d: int
    discount_pct: int
    reason: str


@dataclass
class FlashSaleRecommendation:
    shop_id: int
    generated_at: str
    candidates: list[FlashSaleCandidate]
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    status: str = "draft"


class FlashSaleRecommender:
    """Analisa catálogo e sugere flash sales para produtos parados."""

    def __init__(
        self,
        client: ShopeeClient,
        access_token: str,
        shop_id: int,
        reports_dir: Path = Path("reports"),
        min_stock: int = 20,
        min_days_without_sales: int = 7,
        discount_pct: int = 15,
    ) -> None:
        self.client = client
        self.access_token = access_token
        self.shop_id = shop_id
        self.reports_dir = reports_dir
        self.min_stock = min_stock
        self.min_days_without_sales = min_days_without_sales
        self.discount_pct = discount_pct
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._perf_endpoint_unsupported = False

    def _extract_item_performance_sales(self, data: dict[str, Any]) -> int:
        """Extrai quantidade vendida de um payload de performance com tolerância a formatos diferentes."""
        if not isinstance(data, dict):
            return 0

        response = data.get("response", data)
        if not isinstance(response, dict):
            return 0

        candidate_keys = [
            "sales_7d",
            "sales",
            "total_sold",
            "sold_count",
            "order_count",
            "orders_count",
            "total_orders",
        ]
        for key in candidate_keys:
            value = response.get(key)
            if isinstance(value, (int, float)):
                return int(value)

        nested_paths = [
            ("performance", "sales_7d"),
            ("metrics", "sales_7d"),
            ("summary", "sales"),
            ("data", "sales"),
        ]
        for first, second in nested_paths:
            nested = response.get(first)
            if isinstance(nested, dict):
                value = nested.get(second)
                if isinstance(value, (int, float)):
                    return int(value)

        return 0

    def _extract_item_name(self, item: dict[str, Any]) -> str:
        return str(
            item.get("item_name")
            or item.get("name")
            or item.get("item_title")
            or item.get("product_name")
            or f"item_{item.get('item_id', 'unknown')}"
        )

    def _fetch_items(self, page_size: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            resp = self.client.get_item_list(
                access_token=self.access_token,
                shop_id=self.shop_id,
                offset=offset,
                page_size=page_size,
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            batch = body.get("item", []) if isinstance(body, dict) else []
            if not batch:
                break
            items.extend([item for item in batch if isinstance(item, dict)])
            if len(batch) < page_size:
                break
            offset += page_size
        return items

    def _build_candidate(self, item: dict[str, Any], sales_7d: int) -> FlashSaleCandidate | None:
        try:
            stock = int(item.get("stock", 0) or 0)
        except Exception:
            stock = 0
        if stock < self.min_stock:
            return None
        if sales_7d > 0:
            return None

        item_id_raw = item.get("item_id")
        try:
            item_id = int(item_id_raw)
        except Exception:
            return None

        item_name = self._extract_item_name(item)
        reason = (
            f"Stock alto ({stock}) e sem vendas nos últimos {self.min_days_without_sales} dias"
        )
        return FlashSaleCandidate(
            item_id=item_id,
            item_name=item_name,
            stock=stock,
            sales_7d=sales_7d,
            discount_pct=self.discount_pct,
            reason=reason,
        )

    def generate_recommendations(self) -> FlashSaleRecommendation:
        now = datetime.now(UTC)
        items = self._fetch_items()
        candidates: list[FlashSaleCandidate] = []

        for item in items:
            try:
                item_id = int(item.get("item_id"))
            except Exception:
                continue

            try:
                if self._perf_endpoint_unsupported:
                    sales_7d = 0
                else:
                    perf_resp = self.client.get_item_performance(
                        access_token=self.access_token,
                        shop_id=self.shop_id,
                        item_id=item_id,
                        time_from=int((now - timedelta(days=self.min_days_without_sales)).timestamp()),
                        time_to=int(now.timestamp()),
                    )
                    if perf_resp.status_code == 404 or (
                        isinstance(perf_resp.data, dict) and perf_resp.data.get("error") in (
                            "error_not_found",
                            "error_unknown",
                        )
                    ):
                        self._perf_endpoint_unsupported = True
                        sales_7d = 0
                    else:
                        sales_7d = self._extract_item_performance_sales(perf_resp.data)
            except Exception as exc:
                warning("Failed to fetch item performance", item_id=item_id, error=str(exc)[:160])
                sales_7d = 0

            candidate = self._build_candidate(item, sales_7d)
            if candidate:
                candidates.append(candidate)

        recommendation = FlashSaleRecommendation(
            shop_id=self.shop_id,
            generated_at=now.isoformat(),
            candidates=candidates,
            scheduled_start=(now + timedelta(hours=2)).isoformat(),
            scheduled_end=(now + timedelta(hours=6)).isoformat(),
        )
        self._persist_recommendation(recommendation)
        return recommendation

    def build_flash_sale_payload(self, recommendation: FlashSaleRecommendation) -> dict[str, Any]:
        items = [
            {
                "item_id": candidate.item_id,
                "discount_percentage": candidate.discount_pct,
            }
            for candidate in recommendation.candidates
        ]
        start_time = int(datetime.fromisoformat(recommendation.scheduled_start).timestamp()) if recommendation.scheduled_start else int(datetime.now(UTC).timestamp())
        end_time = int(datetime.fromisoformat(recommendation.scheduled_end).timestamp()) if recommendation.scheduled_end else int((datetime.now(UTC) + timedelta(hours=4)).timestamp())
        return {
            "flash_sale_name": f"Flash Sale automática - {datetime.now(UTC).strftime('%Y%m%d')}",
            "start_time": start_time,
            "end_time": end_time,
            "items": items,
        }

    def create_flash_sale(self, recommendation: FlashSaleRecommendation) -> dict[str, Any]:
        if not recommendation.candidates:
            return {
                "status": "no_candidates",
                "flash_sale": None,
                "candidates": [],
            }

        payload = self.build_flash_sale_payload(recommendation)
        resp = self.client.add_flash_sale(
            access_token=self.access_token,
            shop_id=self.shop_id,
            flash_sale_name=payload["flash_sale_name"],
            start_time=payload["start_time"],
            end_time=payload["end_time"],
            items=payload["items"],
        )
        result = {
            "status": "created" if resp.status_code < 400 else "error",
            "flash_sale": resp.data,
            "payload": payload,
            "candidates": [asdict(candidate) for candidate in recommendation.candidates],
        }
        self._persist_result(result)
        return result

    def _persist_recommendation(self, recommendation: FlashSaleRecommendation) -> None:
        latest_path = self.reports_dir / "laura_flash_sale_recommendation_latest.json"
        history_path = self.reports_dir / "laura_flash_sale_recommendation_history.jsonl"
        payload = json.dumps({
            **asdict(recommendation),
            "candidates": [asdict(candidate) for candidate in recommendation.candidates],
        }, ensure_ascii=False, indent=2)
        latest_path.write_text(payload, encoding="utf-8")
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                **asdict(recommendation),
                "candidates": [asdict(candidate) for candidate in recommendation.candidates],
            }, ensure_ascii=False) + "\n")

    def _persist_result(self, result: dict[str, Any]) -> None:
        out_path = self.reports_dir / "laura_flash_sale_result_latest.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def summarize(self, recommendation: FlashSaleRecommendation) -> dict[str, Any]:
        return {
            "shop_id": recommendation.shop_id,
            "generated_at": recommendation.generated_at,
            "candidate_count": len(recommendation.candidates),
            "total_stock": sum(candidate.stock for candidate in recommendation.candidates),
            "discount_pct": self.discount_pct,
            "status": recommendation.status,
        }
