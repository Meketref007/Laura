from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.flash_sale_executor import FlashSaleExecutor
from shopee_agent.flash_sale_recommender import FlashSaleCandidate, FlashSaleRecommendation


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def executor(mock_client, tmp_path):
    return FlashSaleExecutor(
        client=mock_client,
        access_token="test_token",
        shop_id=12345,
        reports_dir=tmp_path,
    )


@pytest.fixture
def sample_recommendation():
    candidates = [
        FlashSaleCandidate(
            item_id=1001,
            item_name="Product A",
            stock=50,
            sales_7d=0,
            discount_pct=20,
            reason="High stock, no recent sales",
        ),
        FlashSaleCandidate(
            item_id=1002,
            item_name="Product B",
            stock=30,
            sales_7d=2,
            discount_pct=15,
            reason="Stock moderately high",
        ),
    ]
    return FlashSaleRecommendation(
        shop_id=12345,
        generated_at=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
        scheduled_start=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        scheduled_end=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    )


class TestFlashSaleExecutor:
    def test_create_flash_sale(self, executor, mock_client, sample_recommendation):
        mock_client.add_flash_sale.return_value = MagicMock(
            status_code=200,
            data={"flash_sale_id": 5001, "status": "created"},
        )
        result = executor._recommender.create_flash_sale(sample_recommendation)
        assert result["status"] == "created"
        assert "flash_sale" in result

    def test_cancel_flash_sale(self, executor, mock_client):
        mock_client.update_flash_sale.return_value = MagicMock(status_code=200)
        assert executor.cancel_flash_sale(5001) is True
        mock_client.update_flash_sale.assert_called_once_with(
            access_token="test_token",
            shop_id=12345,
            flash_sale_id=5001,
            updates={"status": 0},
        )

    def test_cancel_flash_sale_failure(self, executor, mock_client):
        mock_client.update_flash_sale.side_effect = Exception("API error")
        assert executor.cancel_flash_sale(5001) is False

    def test_list_flash_sales(self, executor, mock_client):
        mock_client.get_flash_sale_list.return_value = MagicMock(
            data={
                "response": {
                    "flash_sale_list": [
                        {"id": 1, "status": 1, "name": "Active Sale"},
                        {"id": 2, "status": 0, "name": "Inactive Sale"},
                    ],
                    "has_more": False,
                }
            }
        )
        active = executor.get_active_flash_sales()
        assert len(active) == 1
        assert active[0]["id"] == 1

    def test_list_flash_sales_empty(self, executor, mock_client):
        mock_client.get_flash_sale_list.return_value = MagicMock(
            data={"response": {"flash_sale_list": [], "has_more": False}}
        )
        assert executor.get_active_flash_sales() == []

    def test_execute_recommendations_pending_approval(self, executor, sample_recommendation):
        result = executor.execute_recommendations(sample_recommendation, auto_approve=False)
        assert result["status"] == "pending_approval"
        assert result["candidate_count"] == 2

    def test_execute_recommendations_auto_approve(self, executor, mock_client, sample_recommendation):
        mock_client.add_flash_sale.return_value = MagicMock(status_code=200, data={"id": 999})
        result = executor.execute_recommendations(sample_recommendation, auto_approve=True)
        assert result["status"] == "completed"
        assert len(result["created"]) == 2

    def test_execute_recommendations_with_errors(self, executor, mock_client, sample_recommendation):
        mock_client.add_flash_sale.side_effect = [MagicMock(status_code=200, data={"id": 1}), Exception("fail")]
        result = executor.execute_recommendations(sample_recommendation, auto_approve=True)
        assert result["created"] == [1001]
        assert result["skipped"] == [1002]
        assert len(result["errors"]) == 1

    def test_schedule_flash_sale(self, executor, mock_client):
        mock_client.add_flash_sale.return_value = MagicMock(status_code=200, data={"flash_sale_id": 6001})
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        end = start + timedelta(hours=4)
        result = executor.schedule_flash_sale(
            item_id=2001,
            discount_pct=25,
            start_time=start,
            end_time=end,
        )
        assert result["status"] == "created"

    def test_get_flash_sale_status(self, executor, mock_client):
        mock_client.get_flash_sale_list.return_value = MagicMock(
            data={
                "response": {
                    "flash_sale_list": [
                        {"id": 10, "status": 1, "name": "Sale 1"},
                        {"id": 11, "status": 1, "name": "Sale 2"},
                    ],
                    "has_more": False,
                }
            }
        )
        active = executor.get_active_flash_sales()
        assert len(active) == 2
        assert all(s["status"] == 1 for s in active)
