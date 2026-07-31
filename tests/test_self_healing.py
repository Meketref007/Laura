from __future__ import annotations

from shopee_agent.self_healing import SelfHealingCoordinator


def test_self_healing_evaluate_returns_snapshot():
    coordinator = SelfHealingCoordinator()
    snapshot = coordinator.evaluate()

    assert snapshot.status in ("healthy", "degraded", "critical")
    assert hasattr(snapshot, "resilience_score")
    assert 0.0 <= snapshot.resilience_score <= 100.0
    assert isinstance(snapshot.recovery_actions, list)


def test_self_healing_run_recovery_plan():
    coordinator = SelfHealingCoordinator()
    result = coordinator.run_recovery_plan(auto_reset=True)

    assert "snapshot" in result
    assert "reset_results" in result
    assert isinstance(result["reset_results"], list)
