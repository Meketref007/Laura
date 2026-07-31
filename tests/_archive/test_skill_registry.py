from shopee_agent.skills.registry import SkillRegistry, Skill, default_registry


def test_register_and_create_custom_skill():
    class TSkill(Skill):
        def run(self, x):
            return x * 2

    r = SkillRegistry()
    r.register(TSkill)
    assert "TSkill" in r.list()
    inst = r.create("TSkill")
    assert inst is not None
    assert inst.run(3) == 6


def test_default_registry_example_skill():
    # import the example skill module so it registers itself in the default registry
    from shopee_agent.skills import example_skill  # noqa: F401

    assert "EchoSkill" in default_registry.list()
    inst = default_registry.create("EchoSkill")
    assert inst is not None
    assert inst.run("ok") == "ok"
