"""Tests for skills package."""

import pytest
from shopee_agent.skills.registry import Skill, SkillRegistry, invoke
from shopee_agent.skills.loader import discover_and_register


class DummySkill(Skill):
    name = "dummy"
    risk_level = "LOW"

    def run(self, x: int = 0) -> dict:
        return {"x": x, "multiplied": x * 2}


def test_skill_registry():
    reg = SkillRegistry()
    reg.register(DummySkill)
    assert reg.list() == ["dummy"]
    skill = reg.create("dummy")
    assert skill is not None
    result = skill.run(x=5)
    assert result == {"x": 5, "multiplied": 10}


@pytest.mark.asyncio
async def test_skill_invoke():
    reg = SkillRegistry()
    reg.register(DummySkill)
    skill = reg.create("dummy")
    result = await invoke(skill, x=3)
    assert result["multiplied"] == 6


def test_discover_and_register():
    reg = SkillRegistry()
    discover_and_register(registry=reg)
    names = reg.list()
    assert "order_ship" in names
    assert "low_stock_alert" in names
    assert "protect_margin" in names
    assert "auto_support" in names


def test_order_ship_skill():
    from shopee_agent.skills.registry import default_registry
    skill = default_registry.create("order_ship")
    assert skill is not None
    result = skill.run(order_sn="test123")
    assert result["order_sn"] == "test123"
    assert "error" in result


def test_low_stock_alert_skill():
    from shopee_agent.skills.registry import default_registry
    skill = default_registry.create("low_stock_alert")
    result = skill.run(item_id="ITEM001", stock=1, threshold=3)
    assert result["alert"] is True
    result2 = skill.run(item_id="ITEM002", stock=10, threshold=3)
    assert result2["alert"] is False


def test_protect_margin_skill():
    from shopee_agent.skills.registry import default_registry
    skill = default_registry.create("protect_margin")
    result = skill.run(item_id="P001", current_price=100.0, min_margin_pct=20.0,
                       context={"current_margin_pct": 15.0})
    assert result["action"] == "protect_margin"


def test_auto_support_skill():
    from shopee_agent.skills.registry import default_registry
    skill = default_registry.create("auto_support")
    result = skill.run(message="Qual o prazo de entrega?", buyer_id="B001")
    assert result["auto_replied"] is True
    assert result["classified_as"] == "prazo"
    result2 = skill.run(message="Quero comprar um produto", buyer_id="B002")
    assert result2["auto_replied"] is False
