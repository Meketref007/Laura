"""Tests for the A/B test automator and statistical functions."""

import math
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def registry():
    reg = MagicMock()
    reg._lock = MagicMock()
    reg._tests = {}
    reg.summary = MagicMock(return_value={})
    return reg


@pytest.fixture
def automator(registry):
    from shopee_agent.ab_test_automator import ABTestAutomator
    return ABTestAutomator(registry)


def test_two_proportion_z_test():
    from shopee_agent.ab_test_automator import two_proportion_z_test
    z, p = two_proportion_z_test(10, 100, 15, 100)
    assert isinstance(z, float)
    assert isinstance(p, float)
    assert 0.0 <= p <= 1.0
    z2, p2 = two_proportion_z_test(0, 0, 0, 0)
    assert z2 == 0.0
    assert p2 == 1.0


def test_normal_cdf():
    from shopee_agent.ab_test_automator import _normal_cdf
    assert abs(_normal_cdf(0.0) - 0.5) < 1e-6
    assert _normal_cdf(-1.0) < 0.5
    assert _normal_cdf(1.0) > 0.5
    assert abs(_normal_cdf(3.0) - 0.99865) < 1e-4


def test_evaluate_and_promote_no_test(automator):
    result = automator.evaluate_and_promote("nonexistent")
    assert result["promoted"] is False
    assert "not found" in result["reason"]


def test_evaluate_and_promote_winner(automator):
    summary = {
        "test_1": {
            "outcomes": {
                "control": {"executions": 100, "successes": 20},
                "variant": {"executions": 100, "successes": 40},
            }
        }
    }
    automator._registry.summary = MagicMock(return_value=summary)
    with patch.object(automator, "_promote_test"):
        result = automator.evaluate_and_promote("test_1", min_confidence=0.9, min_samples=10)
        assert result["promoted"] is True
        assert result["winner"] == "variant"


def test_evaluate_and_promote_insufficient_samples(automator):
    summary = {
        "test_2": {
            "outcomes": {
                "control": {"executions": 3, "successes": 1},
                "variant": {"executions": 2, "successes": 1},
            }
        }
    }
    automator._registry.summary = MagicMock(return_value=summary)
    result = automator.evaluate_and_promote("test_2", min_samples=10)
    assert result["promoted"] is False
    assert "Insufficient" in result["reason"]


def test_evaluate_all(automator):
    summary = {
        "t1": {
            "outcomes": {
                "control": {"executions": 100, "successes": 10},
                "variant": {"executions": 100, "successes": 30},
            }
        }
    }
    automator._registry.summary = MagicMock(return_value=summary)
    with patch.object(automator, "_is_promoted", return_value=False):
        with patch.object(automator, "_promote_test"):
            results = automator.evaluate_all(min_confidence=0.95, min_samples=10)
            assert len(results) == 1
            assert results[0]["test_id"] == "t1"


def test_auto_promote_loop_start_stop(automator):
    assert automator._loop_thread is None
    automator.auto_promote_loop(interval_seconds=0.1)
    assert automator._loop_thread is not None
    assert automator._loop_thread.is_alive()
    automator.stop_loop()
    automator._loop_thread.join(timeout=2)
    assert not automator._loop_thread.is_alive()
