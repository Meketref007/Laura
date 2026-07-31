"""Tests for GOAP Planner."""

import pytest
from shopee_agent.goap_planner import GOAPAction, GOAPPlanner


def test_goap_action_validation():
    action = GOAPAction(
        name="test_action",
        cost=2.0,
        preconditions={"has_item": True},
        effects={"item_processed": True},
    )
    state = {"has_item": True, "item_processed": False}
    assert action.is_valid(state) is True
    state2 = {"has_item": False, "item_processed": False}
    assert action.is_valid(state2) is False


def test_goap_action_effects():
    action = GOAPAction(
        name="process_item",
        effects={"item_processed": True, "has_item": False},
    )
    state = {"has_item": True, "item_processed": False}
    new_state = action.apply_effects(state)
    assert new_state == {"has_item": False, "item_processed": True}


def test_goap_planner_simple_plan():
    planner = GOAPPlanner()
    planner.register_action(GOAPAction(
        name="get_item",
        cost=1.0,
        effects={"has_item": True},
    ))
    planner.register_action(GOAPAction(
        name="process_item",
        cost=2.0,
        preconditions={"has_item": True},
        effects={"item_processed": True, "has_item": False},
    ))
    start = {"has_item": False, "item_processed": False}
    goal = {"has_item": False, "item_processed": True}
    plan = planner.plan(start, goal)
    assert plan is not None
    assert len(plan) == 2
    assert plan[0].name == "get_item"
    assert plan[1].name == "process_item"


def test_goap_planner_no_plan():
    planner = GOAPPlanner()
    planner.register_action(GOAPAction(
        name="unrelated",
        effects={"something": True},
    ))
    start = {"a": False}
    goal = {"a": True}
    plan = planner.plan(start, goal, max_depth=5)
    assert plan is None


def test_goap_planner_cost_ordering():
    planner = GOAPPlanner()
    planner.register_action(GOAPAction(
        name="slow_path",
        cost=10.0,
        effects={"done": True},
    ))
    planner.register_action(GOAPAction(
        name="fast_path",
        cost=1.0,
        effects={"done": True},
    ))
    start = {"done": False}
    goal = {"done": True}
    plan = planner.plan(start, goal)
    assert plan is not None
    assert plan[0].name == "fast_path"


def test_goap_load_skills():
    from shopee_agent.skills.registry import default_registry
    from shopee_agent.skills.loader import discover_and_register
    discover_and_register()
    planner = GOAPPlanner()
    planner.load_skills(default_registry)
    assert len(planner._actions) > 0
