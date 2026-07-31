"""Tests for the Shopee API usage tracker (shopee_agent.api_usage_tracker)."""

import pytest

from shopee_agent.api_usage_tracker import APITracker


@pytest.fixture
def tracker(tmp_path):
    return APITracker(
        db_path=str(tmp_path / "api_usage.db"),
        daily_limit=100,
        warn_pct=0.8,
        alert_pct=0.95,
    )


def test_record_and_counts(tracker):
    tracker.record("product/get_item_list", status=200, latency_ms=12.5)
    tracker.record("product/get_item_list", status=200, latency_ms=7.5)
    tracker.record("order/get_order_list", status=200, latency_ms=30.0)
    tracker.record("order/get_order_list", status=500, latency_ms=50.0)
    counts = tracker.today_counts()
    assert counts["total"] == 4
    assert counts["errors"] == 1
    assert counts["by_endpoint"] == {
        "product/get_item_list": 2,
        "order/get_order_list": 2,
    }


def test_usage_percentage(tracker):
    assert tracker.usage_pct() == 0.0
    for _ in range(25):
        tracker.record("product/get_item_list")
    assert tracker.usage_pct() == pytest.approx(0.25)


def test_warn_threshold(tracker):
    for _ in range(79):
        tracker.record("product/get_item_list")
    assert tracker.should_warn() is False
    tracker.record("product/get_item_list")  # 80 / 100 = 0.8
    assert tracker.should_warn() is True


def test_alert_threshold(tracker):
    for _ in range(94):
        tracker.record("product/get_item_list")
    assert tracker.should_alert() is False
    tracker.record("product/get_item_list")  # 95 / 100 = 0.95
    assert tracker.should_alert() is True


def test_alerts_only_once_per_day(tracker):
    for _ in range(80):
        tracker.record("product/get_item_list")
    assert tracker.should_warn() is True
    assert tracker.should_warn() is False  # already alerted today
    tracker.reset_alerts()
    assert tracker.should_warn() is True


def test_summary(tracker):
    tracker.record("product/get_item_list", latency_ms=10.0)
    tracker.record("order/get_order_list", latency_ms=20.0)
    tracker.record("shop/get_shop_info", latency_ms=30.0)
    rows = tracker.summary(limit=2)
    assert len(rows) == 2
    assert rows[0]["endpoint"] == "shop/get_shop_info"  # newest first
    assert rows[0]["count"] == 1
    assert rows[1]["endpoint"] == "order/get_order_list"
