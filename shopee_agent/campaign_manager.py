from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .client import ShopeeResponse


class CampaignManager:
    def __init__(
        self,
        client: Any,
        access_token: str,
        shop_id: int,
    ) -> None:
        self._client = client
        self._access_token = access_token
        self._shop_id = shop_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_time(dt: datetime) -> int:
        return int(dt.timestamp())

    @staticmethod
    def _to_dict(obj: ShopeeResponse | Any) -> dict[str, Any]:
        if isinstance(obj, ShopeeResponse):
            return obj.data
        if hasattr(obj, "data"):
            return obj.data
        if isinstance(obj, dict):
            return obj
        return {"response": str(obj)}

    # ------------------------------------------------------------------
    # Campaign lifecycle – Bundle Deal
    # ------------------------------------------------------------------

    def create_bundle_deal(
        self,
        name: str,
        items: list[dict[str, Any]],
        discount_pct: float,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        enriched = []
        for item in items:
            enriched.append({
                "item_id": item["item_id"],
                "item_discount": int(discount_pct),
            })
        resp = self._client.add_bundle_deal(
            access_token=self._access_token,
            shop_id=self._shop_id,
            bundle_name=name,
            start_time=self._format_time(start_time),
            end_time=self._format_time(end_time),
            items=enriched,
        )
        return self._to_dict(resp)

    # ------------------------------------------------------------------
    # Campaign lifecycle – Voucher
    # ------------------------------------------------------------------

    def create_voucher(
        self,
        name: str,
        value: float,
        min_spend: float,
        quantity: int,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        resp = self._client.add_voucher(
            access_token=self._access_token,
            shop_id=self._shop_id,
            voucher_name=name,
            voucher_type=1,
            value=value,
            usage_quantity=quantity,
            start_time=self._format_time(start_time),
            end_time=self._format_time(end_time),
            min_spend=min_spend,
        )
        return self._to_dict(resp)

    # ------------------------------------------------------------------
    # Campaign lifecycle – Discount
    # ------------------------------------------------------------------

    def create_discount(
        self,
        items: list[dict[str, Any]],
        discount_pct: float,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        enriched = []
        for item in items:
            enriched.append({
                "item_id": item["item_id"],
                "item_discount_pct": int(discount_pct),
            })
        resp = self._client.add_discount(
            access_token=self._access_token,
            shop_id=self._shop_id,
            discount_name=f"Discount {int(discount_pct)}%",
            start_time=self._format_time(start_time),
            end_time=self._format_time(end_time),
            items=enriched,
        )
        return self._to_dict(resp)

    # ------------------------------------------------------------------
    # Campaign lifecycle – Flash Sale
    # ------------------------------------------------------------------

    def create_flash_sale(
        self,
        items: list[dict[str, Any]],
        discount_pct: float,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        enriched = []
        for item in items:
            enriched.append({
                "item_id": item["item_id"],
                "discount": int(discount_pct),
                "stock": item.get("stock", 1),
            })
        resp = self._client.add_flash_sale(
            access_token=self._access_token,
            shop_id=self._shop_id,
            flash_sale_name=f"Flash Sale {int(discount_pct)}%",
            start_time=self._format_time(start_time),
            end_time=self._format_time(end_time),
            items=enriched,
        )
        return self._to_dict(resp)

    # ------------------------------------------------------------------
    # Campaign lifecycle – Top Picks
    # ------------------------------------------------------------------

    def create_top_picks(
        self,
        name: str,
        item_ids: list[int],
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        enriched = [{"item_id": iid} for iid in item_ids]
        resp = self._client.add_top_picks(
            access_token=self._access_token,
            shop_id=self._shop_id,
            title=name,
            items=enriched,
        )
        return self._to_dict(resp)

    # ------------------------------------------------------------------
    # Campaign lifecycle – Follow Prize
    # ------------------------------------------------------------------

    def create_follow_prize(
        self,
        name: str,
        item_ids: list[int],
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, Any]:
        enriched = [{"item_id": iid} for iid in item_ids]
        resp = self._client.add_follow_prize(
            access_token=self._access_token,
            shop_id=self._shop_id,
            follow_prize_name=name,
            start_time=self._format_time(start_time),
            end_time=self._format_time(end_time),
            items=enriched,
        )
        return self._to_dict(resp)

    # ------------------------------------------------------------------
    # Campaign monitoring
    # ------------------------------------------------------------------

    def list_active_campaigns(self) -> list[dict[str, Any]]:
        int(datetime.now().timestamp())
        campaigns: list[dict[str, Any]] = []

        try:
            resp = self._client.get_discount_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
                discount_status="ongoing",
            )
            data = self._to_dict(resp)
            for item in data.get("discount_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "discount"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_voucher_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
                status="ongoing",
            )
            data = self._to_dict(resp)
            for item in data.get("voucher_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "voucher"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_bundle_deal_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
            data = self._to_dict(resp)
            for item in data.get("bundle_deal_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "bundle_deal"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_flash_sale_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
            data = self._to_dict(resp)
            for item in data.get("flash_sale_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "flash_sale"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_top_picks_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
            data = self._to_dict(resp)
            for item in data.get("top_picks_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "top_picks"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_follow_prize_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
            data = self._to_dict(resp)
            for item in data.get("follow_prize_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "follow_prize"
                    campaigns.append(item)
        except Exception:
            pass

        return campaigns

    def get_campaign_stats(
        self,
        campaign_type: str,
        campaign_id: int,
    ) -> dict[str, Any]:
        if campaign_type == "discount":
            resp = self._client.get_discount_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
        elif campaign_type == "voucher":
            resp = self._client.get_voucher_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
        elif campaign_type == "bundle_deal":
            resp = self._client.get_bundle_deal_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
        elif campaign_type == "flash_sale":
            resp = self._client.get_flash_sale_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
        elif campaign_type == "top_picks":
            resp = self._client.get_top_picks_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
        elif campaign_type == "follow_prize":
            resp = self._client.get_follow_prize_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
        else:
            return {"error": f"Unknown campaign type: {campaign_type}"}

        data = self._to_dict(resp)
        stat = {"campaign_type": campaign_type, "campaign_id": campaign_id}
        stat["found"] = False
        for item in data.get("response", []):
            if isinstance(item, dict) and item.get("campaign_id") == campaign_id:
                stat.update(item)
                stat["found"] = True
                break
        return stat

    def get_upcoming_campaigns(self, days: int = 7) -> list[dict[str, Any]]:
        now = int(datetime.now().timestamp())
        cutoff = int((datetime.now() + timedelta(days=days)).timestamp())
        campaigns: list[dict[str, Any]] = []

        try:
            resp = self._client.get_discount_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
                discount_status="upcoming",
            )
            data = self._to_dict(resp)
            for item in data.get("discount_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "discount"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_voucher_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
                status="upcoming",
            )
            data = self._to_dict(resp)
            for item in data.get("voucher_list", data.get("response", [])):
                if isinstance(item, dict):
                    item["_type"] = "voucher"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_bundle_deal_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
            data = self._to_dict(resp)
            for item in data.get("bundle_deal_list", data.get("response", [])):
                if isinstance(item, dict) and item.get("start_time", 0) >= now and item.get("start_time", 0) <= cutoff:
                    item["_type"] = "bundle_deal"
                    campaigns.append(item)
        except Exception:
            pass

        try:
            resp = self._client.get_flash_sale_list(
                access_token=self._access_token,
                shop_id=self._shop_id,
            )
            data = self._to_dict(resp)
            for item in data.get("flash_sale_list", data.get("response", [])):
                if isinstance(item, dict) and item.get("start_time", 0) >= now and item.get("start_time", 0) <= cutoff:
                    item["_type"] = "flash_sale"
                    campaigns.append(item)
        except Exception:
            pass

        return campaigns

    # ------------------------------------------------------------------
    # Campaign optimization
    # ------------------------------------------------------------------

    def suggest_optimal_discount(
        self,
        item_id: int,
        current_price: float,
        margin_pct: float,
    ) -> dict[str, Any]:
        suggested_pct = max(0, margin_pct - 10)
        max_discount_pct = margin_pct * 0.8
        safe_discount_pct = min(suggested_pct, max_discount_pct)
        discounted_price = current_price * (1 - safe_discount_pct / 100)
        return {
            "item_id": item_id,
            "current_price": current_price,
            "margin_pct": margin_pct,
            "suggested_discount_pct": round(safe_discount_pct, 2),
            "suggested_price": round(discounted_price, 2),
            "max_discount_pct": round(max_discount_pct, 2),
            "risk_level": "low" if safe_discount_pct <= margin_pct * 0.5 else "medium",
        }

    def auto_campaign_from_metrics(
        self,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []

        stock = metrics.get("stock", 0)
        days_without_sale = metrics.get("days_without_sale", 0)
        margin = metrics.get("margin_pct", 0)
        inventory_value = metrics.get("inventory_value", 0)
        item_id = metrics.get("item_id", 0)
        item_name = metrics.get("item_name", f"Item {item_id}")

        if stock > 50 and days_without_sale > 7:
            suggestions.append({
                "type": "flash_sale",
                "item_id": item_id,
                "item_name": item_name,
                "reason": f"Stock ({stock}) > 50 and {days_without_sale} days without sale",
                "discount_pct": 20,
                "priority": "high",
            })

        if margin > 30:
            suggestions.append({
                "type": "voucher",
                "item_id": item_id,
                "item_name": item_name,
                "reason": f"Margin ({margin}%) > 30%",
                "value": margin * 0.1,
                "min_spend": 0,
                "quantity": 100,
                "priority": "medium",
            })

        if inventory_value > 10000:
            suggestions.append({
                "type": "bundle_deal",
                "item_id": item_id,
                "item_name": item_name,
                "reason": f"Inventory value ({inventory_value}) > 10000",
                "discount_pct": 15,
                "priority": "medium",
            })

        return suggestions
