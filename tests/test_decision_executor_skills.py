"""Tests for DecisionExecutor skill integration."""

import pytest
from unittest.mock import MagicMock, patch
from shopee_agent.decision_integration import DecisionExecutor
from shopee_agent.goap_planner import GOAPAction


@pytest.fixture
def executor():
    return DecisionExecutor(store_id="test_store")


def test_execute_skill_action_not_found(executor):
    result = executor.execute_skill_action("nonexistent_skill")
    assert result is None


def test_execute_goap_plan_empty(executor):
    results = executor.execute_goap_plan([])
    assert results == []


def test_execute_goap_plan_with_skills(executor):
    from shopee_agent.skills.registry import default_registry
    from shopee_agent.skills.loader import discover_and_register
    discover_and_register()

    action = GOAPAction(name="low_stock_alert", effects={"stock_checked": True})
    results = executor.execute_goap_plan([action])
    assert len(results) == 1
    assert results[0] is True
