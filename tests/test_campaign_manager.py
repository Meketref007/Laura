from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from shopee_agent.campaign_manager import CampaignManager
from shopee_agent.client import ShopeeResponse


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def manager(mock_client):
    return CampaignManager(
        client=mock_client,
        access_token="token123",
        shop_id=999,
    )


def _dt():
    return datetime(2026, 7, 30, 12, 0, 0)


def _resp(data: dict, status: int = 200) -> ShopeeResponse:
    return ShopeeResponse(status_code=status, data=data)


class TestCampaignManager:
    def test_create_bundle_deal(self, manager, mock_client):
        mock_client.add_bundle_deal.return_value = _resp({"bundle_deal_id": 101})
        items = [{"item_id": 1}, {"item_id": 2}]
        result = manager.create_bundle_deal("Bundle 1", items, 15, _dt(), _dt() + timedelta(days=1))
        assert result["bundle_deal_id"] == 101
        mock_client.add_bundle_deal.assert_called_once()

    def test_create_voucher(self, manager, mock_client):
        mock_client.add_voucher.return_value = _resp({"voucher_id": 202})
        result = manager.create_voucher("Voucher 1", 10.0, 50.0, 100, _dt(), _dt() + timedelta(days=1))
        assert result["voucher_id"] == 202
        mock_client.add_voucher.assert_called_once()

    def test_create_discount(self, manager, mock_client):
        mock_client.add_discount.return_value = _resp({"discount_id": 303})
        items = [{"item_id": 1}, {"item_id": 2}]
        result = manager.create_discount(items, 20, _dt(), _dt() + timedelta(days=1))
        assert result["discount_id"] == 303

    def test_create_flash_sale(self, manager, mock_client):
        mock_client.add_flash_sale.return_value = _resp({"flash_sale_id": 404})
        items = [{"item_id": 1, "stock": 10}, {"item_id": 2}]
        result = manager.create_flash_sale(items, 25, _dt(), _dt() + timedelta(days=1))
        assert result["flash_sale_id"] == 404

    def test_list_active_campaigns(self, manager, mock_client):
        mock_client.get_discount_list.return_value = _resp({
            "discount_list": [{"campaign_id": 1, "name": "D1"}]
        })
        mock_client.get_voucher_list.return_value = _resp({
            "voucher_list": [{"campaign_id": 2, "name": "V1"}]
        })
        mock_client.get_bundle_deal_list.return_value = _resp({
            "bundle_deal_list": [{"campaign_id": 3, "name": "B1"}]
        })
        mock_client.get_flash_sale_list.return_value = _resp({
            "flash_sale_list": [{"campaign_id": 4, "name": "FS1"}]
        })
        mock_client.get_top_picks_list.return_value = _resp({
            "top_picks_list": [{"campaign_id": 5, "name": "TP1"}]
        })
        mock_client.get_follow_prize_list.return_value = _resp({
            "follow_prize_list": [{"campaign_id": 6, "name": "FP1"}]
        })

        campaigns = manager.list_active_campaigns()
        assert len(campaigns) == 6
        types = {c["_type"] for c in campaigns}
        assert types == {"discount", "voucher", "bundle_deal", "flash_sale", "top_picks", "follow_prize"}

    def test_list_active_campaigns_handles_errors(self, manager, mock_client):
        mock_client.get_discount_list.side_effect = Exception("fail")
        mock_client.get_voucher_list.side_effect = Exception("fail")
        mock_client.get_bundle_deal_list.side_effect = Exception("fail")
        mock_client.get_flash_sale_list.side_effect = Exception("fail")
        mock_client.get_top_picks_list.side_effect = Exception("fail")
        mock_client.get_follow_prize_list.side_effect = Exception("fail")
        assert manager.list_active_campaigns() == []

    def test_get_campaign_stats(self, manager, mock_client):
        mock_client.get_discount_list.return_value = _resp({
            "response": [{"campaign_id": 10, "name": "Found Campaign"}]
        })
        result = manager.get_campaign_stats("discount", 10)
        assert result["found"] is True
        assert result["name"] == "Found Campaign"

    def test_get_campaign_stats_not_found(self, manager, mock_client):
        mock_client.get_discount_list.return_value = _resp({"response": []})
        result = manager.get_campaign_stats("discount", 999)
        assert result["found"] is False

    def test_get_campaign_stats_unknown_type(self, manager, mock_client):
        result = manager.get_campaign_stats("unknown_type", 1)
        assert "error" in result

    def test_get_upcoming_campaigns(self, manager, mock_client):
        mock_client.get_discount_list.return_value = _resp({"discount_list": []})
        mock_client.get_voucher_list.return_value = _resp({"voucher_list": []})
        mock_client.get_bundle_deal_list.return_value = _resp({"bundle_deal_list": []})
        mock_client.get_flash_sale_list.return_value = _resp({"flash_sale_list": []})
        assert manager.get_upcoming_campaigns(days=7) == []

    def test_suggest_optimal_discount(self, manager):
        result = manager.suggest_optimal_discount(item_id=1, current_price=100.0, margin_pct=40)
        assert result["item_id"] == 1
        assert result["suggested_discount_pct"] <= result["max_discount_pct"]
        assert "risk_level" in result

    def test_suggest_optimal_discount_low_margin(self, manager):
        result = manager.suggest_optimal_discount(item_id=2, current_price=50.0, margin_pct=5)
        assert result["suggested_discount_pct"] == 0
        assert result["risk_level"] == "low"

    def test_auto_campaign_from_metrics_flash_sale(self, manager):
        metrics = {"item_id": 1, "item_name": "Test", "stock": 100, "days_without_sale": 14, "margin_pct": 25, "inventory_value": 5000}
        suggestions = manager.auto_campaign_from_metrics(metrics)
        types = {s["type"] for s in suggestions}
        assert "flash_sale" in types

    def test_auto_campaign_from_metrics_voucher(self, manager):
        metrics = {"item_id": 2, "stock": 10, "days_without_sale": 1, "margin_pct": 40, "inventory_value": 1000}
        suggestions = manager.auto_campaign_from_metrics(metrics)
        types = {s["type"] for s in suggestions}
        assert "voucher" in types

    def test_auto_campaign_from_metrics_bundle_deal(self, manager):
        metrics = {"item_id": 3, "stock": 5, "days_without_sale": 1, "margin_pct": 20, "inventory_value": 50000}
        suggestions = manager.auto_campaign_from_metrics(metrics)
        types = {s["type"] for s in suggestions}
        assert "bundle_deal" in types

    def test_auto_campaign_from_metrics_no_suggestions(self, manager):
        metrics = {"item_id": 4, "stock": 5, "days_without_sale": 1, "margin_pct": 10, "inventory_value": 100}
        assert manager.auto_campaign_from_metrics(metrics) == []
