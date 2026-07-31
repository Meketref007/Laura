"""
flash_sale_executor.py - Automatic flash sale execution engine

Extends the flash_sale_recommender module with programmatic
flash sale creation, scheduling, querying, and cancellation.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import ShopeeClient
from .flash_sale_recommender import FlashSaleCandidate, FlashSaleRecommendation, FlashSaleRecommender
from .logger import warning


class FlashSaleExecutor:
    """Executes, schedules, queries, and cancels flash sales programmatically."""

    def __init__(
        self,
        client: ShopeeClient,
        access_token: str,
        shop_id: int,
        reports_dir: Path = Path("reports"),
    ) -> None:
        self.client = client
        self.access_token = access_token
        self.shop_id = shop_id
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._recommender = FlashSaleRecommender(
            client=client,
            access_token=access_token,
            shop_id=shop_id,
            reports_dir=reports_dir,
        )

    def execute_recommendations(
        self,
        recommendation: FlashSaleRecommendation,
        auto_approve: bool = False,
    ) -> dict[str, Any]:
        if not auto_approve:
            summary = {
                "status": "pending_approval",
                "shop_id": recommendation.shop_id,
                "generated_at": recommendation.generated_at,
                "candidate_count": len(recommendation.candidates),
                "candidates": [asdict(c) for c in recommendation.candidates],
            }
            self._persist_summary(summary)
            return summary

        created: list[int] = []
        skipped: list[int] = []
        errors: list[dict[str, Any]] = []

        for candidate in recommendation.candidates:
            single = FlashSaleRecommendation(
                shop_id=recommendation.shop_id,
                generated_at=recommendation.generated_at,
                candidates=[candidate],
                scheduled_start=recommendation.scheduled_start,
                scheduled_end=recommendation.scheduled_end,
            )
            try:
                result = self._recommender.create_flash_sale(single)
            except Exception as exc:
                warning("execute_recommendations", item_id=candidate.item_id, error=str(exc)[:200])
                errors.append({"item_id": candidate.item_id, "error": str(exc)[:200]})
                skipped.append(candidate.item_id)
                continue

            if result.get("status") == "created":
                created.append(candidate.item_id)
            else:
                skipped.append(candidate.item_id)

        summary = {
            "status": "completed",
            "shop_id": recommendation.shop_id,
            "generated_at": recommendation.generated_at,
            "created": created,
            "skipped": skipped,
            "errors": errors,
            "created_count": len(created),
            "skipped_count": len(skipped),
            "error_count": len(errors),
        }
        self._persist_summary(summary)
        return summary

    def schedule_flash_sale(
        self,
        item_id: int,
        discount_pct: int,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        candidate = FlashSaleCandidate(
            item_id=item_id,
            item_name=f"item_{item_id}",
            stock=0,
            sales_7d=0,
            discount_pct=discount_pct,
            reason="Scheduled manually via FlashSaleExecutor",
        )
        recommendation = FlashSaleRecommendation(
            shop_id=self.shop_id,
            generated_at=datetime.now(UTC).isoformat(),
            candidates=[candidate],
            scheduled_start=start_time.isoformat(),
            scheduled_end=end_time.isoformat(),
        )
        return self._recommender.create_flash_sale(recommendation)

    def get_active_flash_sales(self) -> list[dict[str, Any]]:
        all_sales: list[dict[str, Any]] = []
        cursor = ""
        while True:
            resp = self.client.get_flash_sale_list(
                access_token=self.access_token,
                shop_id=self.shop_id,
                cursor=cursor,
            )
            body = resp.data.get("response", {}) if isinstance(resp.data, dict) else {}
            batch = body.get("flash_sale_list", []) if isinstance(body, dict) else []
            if not batch:
                break
            all_sales.extend(s for s in batch if isinstance(s, dict))
            if not body.get("has_more", False):
                break
            cursor = body.get("next_cursor", "")
        return [s for s in all_sales if s.get("status") == 1]

    def cancel_flash_sale(self, flash_sale_id: int) -> bool:
        try:
            resp = self.client.update_flash_sale(
                access_token=self.access_token,
                shop_id=self.shop_id,
                flash_sale_id=flash_sale_id,
                updates={"status": 0},
            )
            return resp.status_code < 400
        except Exception as exc:
            warning("cancel_flash_sale", flash_sale_id=flash_sale_id, error=str(exc)[:200])
            return False

    def _persist_summary(self, summary: dict[str, Any]) -> None:
        out_path = self.reports_dir / "laura_flash_sale_executor_summary_latest.json"
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
