"""Tests for the alert system."""

import json
import pytest
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime, timezone, timedelta


@pytest.fixture
def engine(tmp_path):
    from shopee_agent.alerts import AlertsEngine
    eng = AlertsEngine(history_dir=str(tmp_path))
    return eng


def test_alert_creation():
    from shopee_agent.alerts import Alert, AlertRule, AlertSeverity
    alert = Alert(
        rule=AlertRule.LOW_MARGIN,
        severity=AlertSeverity.CRITICAL,
        title="Test Alert",
        message="Test message",
    )
    assert alert.rule == AlertRule.LOW_MARGIN
    assert alert.severity == AlertSeverity.CRITICAL
    assert alert.title == "Test Alert"
    assert alert.message == "Test message"
    assert alert.timestamp is not None


def test_alert_dispatch(engine):
    from shopee_agent.alerts import Alert, AlertRule, AlertSeverity
    alert = Alert(
        rule=AlertRule.LOW_MARGIN,
        severity=AlertSeverity.CRITICAL,
        title="Test",
        message="Test dispatch",
    )
    webhooks = {AlertSeverity.CRITICAL: ["https://hooks.example.com/alert"]}
    with patch("shopee_agent.alerts.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        results = engine.dispatch([alert], webhooks)
        assert results["sent"] == 1
        assert results["failed"] == 0


def test_alert_severity_levels():
    from shopee_agent.alerts import AlertSeverity
    assert AlertSeverity.CRITICAL.value == "CRITICAL"
    assert AlertSeverity.WARNING.value == "WARNING"
    assert AlertSeverity.INFO.value == "INFO"


def test_alert_persistence(engine):
    from shopee_agent.alerts import Alert, AlertRule, AlertSeverity
    alert = Alert(
        rule=AlertRule.LOW_MARGIN,
        severity=AlertSeverity.WARNING,
        title="Persist",
        message="Persist test",
    )
    engine._log_alert(alert)
    history = engine.get_history()
    assert len(history) >= 1
    assert history[-1]["title"] == "Persist"


def test_alert_stats(engine):
    from shopee_agent.alerts import Alert, AlertRule, AlertSeverity, AlertConfig, get_default_alert_config
    config = get_default_alert_config()
    metrics = {
        "margin_pct": 3.0,
        "refund_rate_pct": 1.0,
        "roas": 2.5,
        "order_volume": 10,
        "orders_count": 10,
    }
    alerts = engine.evaluate(metrics, config)
    assert isinstance(alerts, list)
    alert_rules = [a.rule for a in alerts]
    assert AlertRule.LOW_MARGIN in alert_rules
