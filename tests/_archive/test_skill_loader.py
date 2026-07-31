from shopee_agent.skills.loader import discover_and_register
from shopee_agent.skills.registry import SkillRegistry


def test_discover_and_register_registers_example_skill():
    r = SkillRegistry()
    discover_and_register("shopee_agent.skills", registry=r)
    assert "EchoSkill" in r.list()
