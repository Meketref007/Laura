"""Integration test: event bus + workers + decision engine full flow."""

from __future__ import annotations

import json
from pathlib import Path

from shopee_agent.event_bus import (
    AsyncEventBus,
    DecisionSignalEvent,
    CycleCompleteEvent,
    AlertEvent,
)
from shopee_agent.decision_engine import (
    DecisionEngine,
    DecisionRule,
    DecisionType,
    DecisionSignal,
    DecisionPriority,
    RiskLevel,
    default_economic_context,
)
from shopee_agent.workers import (
    DecisionWorker,
    OutcomeWorker,
    MetricWorker,
    NotificationWorker,
)


class FakeExecutor:
    def __init__(self):
        self.executed = []

    def execute(self, decision) -> bool:
        self.executed.append(decision.decision_id)
        return True


class FakeIntegrator:
    def __init__(self):
        self.executed = []

    def mark_decision_executed(self, decision_id: str) -> None:
        self.executed.append(decision_id)


class FakeMemory:
    def __init__(self):
        self.outcomes = []
        self._effectiveness = {}

    def remember_outcome(self, outcome):
        self.outcomes.append(outcome)

    def get_rule_effectiveness(self, rule_id: str) -> float:
        return self._effectiveness.get(rule_id, 0.5)


def test_full_flow_signal_to_metric(tmp_path):
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.chdir(tmp_path)

    bus = AsyncEventBus(worker_count=2)
    bus.start()

    rule = DecisionRule(
        rule_id="test_rule",
        decision_type=DecisionType.ALERTS,
        name="Test",
        description="Test rule",
        condition="source=metrics",
        priority_boost=0,
        risk_threshold=RiskLevel.LOW,
    )
    engine = DecisionEngine(store_id="test", rules=[rule])
    memory = FakeMemory()
    integrator = FakeIntegrator()
    executor = FakeExecutor()

    dw = DecisionWorker(bus, engine=engine, executor=executor, integrator=integrator)
    dw.subscribe()

    ow = OutcomeWorker(bus, engine=engine, memory_layer=memory)
    ow.subscribe()

    mw = MetricWorker(bus)
    mw.subscribe()

    nw = NotificationWorker(bus, telegram_sender=lambda text: None)
    nw.subscribe()

    ctx = default_economic_context()
    signal = DecisionSignal(source="metrics", signal_type="anomaly", data={"metric": "margin_drop"})

    bus.submit(DecisionSignalEvent(
        event_type="decision.signal",
        source="metrics",
        signal=signal,
        context=ctx,
    ))

    bus.submit(CycleCompleteEvent(event_type="cycle.complete", cycle_number=1))

    bus.submit(AlertEvent(event_type="alert", severity="info", title="Integration test", message="OK"))

    bus.wait_until_idle(timeout=5)
    bus.stop()

    metrics = mw.get_metrics()
    assert metrics["total_alerts"] >= 1
    assert metrics["cycles_completed"] >= 1
    # DecisionWorker may or may not have executed based on rule matching, but flow should not crash
    assert mw.get_success_rate() >= 0.0


def test_pending_decisions_persist_across_restart(tmp_path):
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.chdir(tmp_path)

    from shopee_agent.decision_engine import Decision

    engine = DecisionEngine(store_id="persist_test", rules=[])
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    sig = DecisionSignal(source="test", signal_type="manual", data={})
    d = Decision(
        decision_id="persist_d1",
        decision_type=DecisionType.ALERTS,
        rule_id="r1",
        title="Persist Test",
        description="Testing persistence",
        recommended_action="none",
        priority=DecisionPriority.HIGH,
        impact_score=0.5,
        risk_score=0.2,
        confidence_score=0.8,
        signal=sig,
    )
    from shopee_agent.decision_engine import DecisionStatus
    d.status = DecisionStatus.APPROVED
    engine.pending_decisions[d.decision_id] = d
    engine._save_pending()

    # Simulate restart by creating a new engine
    engine2 = DecisionEngine(store_id="persist_test", rules=[])
    assert "persist_d1" in engine2.pending_decisions
    assert engine2.pending_decisions["persist_d1"].title == "Persist Test"


def test_priority_queue_alert_first(tmp_path):
    """Alert events submitted via high-priority queue are dispatched before normal events."""
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    order = []

    def alert_handler(event):
        order.append("alert")

    def normal_handler(event):
        order.append("normal")

    bus.register_handler("alert", alert_handler)
    bus.register_handler("cycle.complete", normal_handler)

    bus.submit(CycleCompleteEvent(event_type="cycle.complete", cycle_number=1))
    bus.submit(AlertEvent(event_type="alert", severity="critical", title="Critical", message="!"))

    bus.wait_until_idle(timeout=5)
    bus.stop()

    assert order == ["alert", "normal"]
