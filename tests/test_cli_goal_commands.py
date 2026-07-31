from __future__ import annotations

from shopee_agent import cli


def test_build_parser_includes_goal_commands():
    parser = cli.build_parser()

    args = parser.parse_args([
        "goal-add",
        "Improve ROAS",
        "boost_ad_efficiency",
        "--metric",
        "roas=2.5",
        "--budget",
        "1500",
        "--days",
        "30",
        "--priority",
        "1",
        "--tag",
        "ads",
        "--store-id",
        "shop-1",
    ])

    assert args.command == "goal-add"
    assert args.name == "Improve ROAS"
    assert args.objective == "boost_ad_efficiency"
    assert args.metrics == ["roas=2.5"]
    assert args.budget == 1500.0
    assert args.days == 30
    assert args.priority == 1
    assert args.tags == ["ads"]
    assert args.store_id == "shop-1"


def test_main_dispatches_goal_summary_without_loading_shopee_config(monkeypatch):
    captured: dict[str, object] = {}

    class FakeGoal:
        def to_dict(self):
            return {"goal_id": "goal_1", "name": "Improve ROAS", "status": "active"}

    class FakeGoalManager:
        def snapshot(self, context=None, priority_engine=None):
            return {"top_goal": {"name": "Improve ROAS"}}

    class FakeIntegrator:
        goal_manager = FakeGoalManager()
        priority_engine = object()

        def build_economic_context(self):
            return None

    def fake_load_integrator(store_id: str = "default"):
        captured["store_id"] = store_id
        return FakeIntegrator()

    monkeypatch.setattr(cli, "initialize_default_circuit_breakers", lambda: None)
    monkeypatch.setattr(cli, "load_config", lambda: (_ for _ in ()).throw(AssertionError("load_config should not run")))
    monkeypatch.setattr("shopee_agent.decision_cli.load_integrator", fake_load_integrator)
    monkeypatch.setattr(cli.sys, "argv", ["laura", "goal-summary", "--store-id", "shop-1"])

    exit_code = cli.main()

    assert exit_code == 0
    assert captured["store_id"] == "shop-1"
