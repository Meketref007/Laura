from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.refunds import (
    RefundManager,
    Refund,
    RefundStats,
    RefundStatus,
    RefundReason,
    RefundDecision,
    create_refund_manager,
)


@pytest.fixture
def refund():
    return Refund(
        refund_id="R001",
        order_id="O001",
        buyer_id="B001",
        product_id="P001",
        reason=RefundReason.DAMAGED_IN_TRANSIT,
        status=RefundStatus.PENDING,
        amount=150.0,
        requested_at=datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture
def manager(tmp_path):
    return RefundManager(history_dir=str(tmp_path))


class TestRefundDecision:
    def test_approve_obvious_reason(self, manager, refund):
        decision = manager.evaluate_refund(refund, {}, {"total_orders": 1, "total_refunds": 0})
        assert decision == RefundDecision.AUTO_APPROVE

    def test_approve_good_buyer(self, manager):
        r = Refund(
            refund_id="R002", order_id="O002", buyer_id="B002",
            product_id="P002", reason=RefundReason.CHANGED_MIND,
            status=RefundStatus.PENDING, amount=50.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        decision = manager.evaluate_refund(r, {}, {"total_orders": 100, "total_refunds": 1})
        assert decision == RefundDecision.AUTO_APPROVE

    def test_reject_suspicious_buyer(self, manager):
        r = Refund(
            refund_id="R003", order_id="O003", buyer_id="B003",
            product_id="P003", reason=RefundReason.CHANGED_MIND,
            status=RefundStatus.PENDING, amount=200.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        decision = manager.evaluate_refund(r, {}, {"total_orders": 3, "total_refunds": 5})
        assert decision == RefundDecision.MANUAL_REVIEW

    def test_escalate_contact_buyer(self, manager):
        r = Refund(
            refund_id="R004", order_id="O004", buyer_id="B004",
            product_id="P004", reason=RefundReason.BETTER_PRICE_ELSEWHERE,
            status=RefundStatus.PENDING, amount=30.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        decision = manager.evaluate_refund(
            r, {"refund_rate_pct": 5.0}, {"total_orders": 10, "total_refunds": 1}
        )
        assert decision == RefundDecision.CONTACT_BUYER

    def test_approve_high_refund_product(self, manager):
        r = Refund(
            refund_id="R005", order_id="O005", buyer_id="B005",
            product_id="P005", reason=RefundReason.CHANGED_MIND,
            status=RefundStatus.PENDING, amount=75.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        decision = manager.evaluate_refund(
            r, {"refund_rate_pct": 20.0}, {"total_orders": 100, "total_refunds": 1}
        )
        assert decision == RefundDecision.AUTO_APPROVE


class TestRefundManager:
    def test_create(self, tmp_path):
        mgr = RefundManager(history_dir=str(tmp_path))
        assert mgr.history_dir.exists()

    def test_create_refund_manager_factory(self, tmp_path):
        with patch("shopee_agent.refunds.RefundManager") as MockRM:
            MockRM.return_value = MagicMock()
            result = create_refund_manager()
            assert result is not None

    def test_process_refund_approve(self, manager, refund):
        result = manager.process_refund(refund, RefundDecision.AUTO_APPROVE, send_message=True)
        assert result["decision"] == "auto_approve"
        assert "approve_refund" in result["actions"]
        assert "process_payment" in result["actions"]
        assert result["message_sent"] is True
        assert refund.status == RefundStatus.APPROVED

    def test_process_refund_reject(self, manager, refund):
        result = manager.process_refund(refund, RefundDecision.AUTO_REJECT, send_message=True)
        assert result["decision"] == "auto_reject"
        assert "reject_refund" in result["actions"]
        assert result["message_sent"] is True
        assert refund.status == RefundStatus.REJECTED

    def test_process_refund_escalate(self, manager, refund):
        result = manager.process_refund(refund, RefundDecision.MANUAL_REVIEW, send_message=False)
        assert result["decision"] == "manual_review"
        assert "flag_for_review" in result["actions"]
        assert result["message_sent"] is False

    def test_process_refund_contact_buyer(self, manager, refund):
        result = manager.process_refund(refund, RefundDecision.CONTACT_BUYER, send_message=True)
        assert result["decision"] == "contact_buyer"
        assert "send_inquiry_message" in result["actions"]
        assert result["message_sent"] is True

    def test_get_stats_empty(self, manager):
        stats = manager.get_refund_stats(days=30)
        assert stats.total_refunds == 0
        assert stats.pending_count == 0
        assert stats.estimated_loss == 0.0

    def test_get_stats_with_data(self, manager):
        r = Refund(
            refund_id="R010", order_id="O010", buyer_id="B010",
            product_id="P010", reason=RefundReason.DAMAGED_IN_TRANSIT,
            status=RefundStatus.APPROVED, amount=100.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
            resolved_at=datetime.now(timezone.utc).isoformat(),
        )
        manager._log_refund(r)

        stats = manager.get_refund_stats(days=30)
        assert stats.total_refunds == 1
        assert stats.pending_count == 0

    def test_get_history(self, manager):
        r = Refund(
            refund_id="R020", order_id="O020", buyer_id="B020",
            product_id="P020", reason=RefundReason.WRONG_ITEM,
            status=RefundStatus.PENDING, amount=200.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        manager._log_refund(r)
        history = manager.get_history(limit=10)
        assert len(history) == 1
        assert history[0]["refund_id"] == "R020"

    def test_get_history_with_filter(self, manager):
        r1 = Refund(
            refund_id="R030", order_id="O030", buyer_id="B030",
            product_id="P030", reason=RefundReason.CHANGED_MIND,
            status=RefundStatus.APPROVED, amount=50.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        r2 = Refund(
            refund_id="R031", order_id="O031", buyer_id="B031",
            product_id="P031", reason=RefundReason.OTHER,
            status=RefundStatus.PENDING, amount=80.0,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        manager._log_refund(r1)
        manager._log_refund(r2)
        history = manager.get_history(limit=10, status_filter="pending")
        assert len(history) == 1
        assert history[0]["refund_id"] == "R031"

    def test_process_refund_mock(self, manager, refund):
        with patch.object(manager, "_log_refund") as mock_log:
            result = manager.process_refund(refund, RefundDecision.AUTO_APPROVE)
            mock_log.assert_called_once()
            assert result["status"] == "processed"
