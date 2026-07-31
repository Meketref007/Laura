from __future__ import annotations

import json

from click.testing import CliRunner

from shopee_agent.decision_cli import decision_cli
from shopee_agent.goal_management import GoalManager, PriorityEngine


class FakeIntegrator:
    def __init__(self, manager: GoalManager):
        self.goal_manager = manager
        self.priority_engine = PriorityEngine()

    def build_economic_context(self):
        return None


def test_goal_cli_add_list_and_top(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = GoalManager(path=str(tmp_path / "reports" / "goals_state.jsonl"))
    integrator = FakeIntegrator(manager)
    monkeypatch.setattr("shopee_agent.decision_cli.load_integrator", lambda store_id="default": integrator)

    runner = CliRunner()

    add_result = runner.invoke(
        decision_cli,
        [
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
        ],
    )
    assert add_result.exit_code == 0

    payload = json.loads(add_result.output)
    assert payload["name"] == "Improve ROAS"
    assert payload["status"] == "active"

    list_result = runner.invoke(decision_cli, ["goal-list"])
    assert list_result.exit_code == 0
    assert "Improve ROAS" in list_result.output

    top_result = runner.invoke(decision_cli, ["goal-top"])
    assert top_result.exit_code == 0
    top_payload = json.loads(top_result.output)
    assert top_payload["name"] == "Improve ROAS"
