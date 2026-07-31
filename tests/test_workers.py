from __future__ import annotations

from pathlib import Path

from shopee_agent.event_bus import (
    AsyncEventBus,
    Event,
    DecisionSignalEvent,
    DecisionExecutedEvent,
    OutcomeRecordedEvent,
    CycleCompleteEvent,
    AlertEvent,
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


class FakeEngine:
    def __init__(self):
        self.pending_decisions = {}
        self.rules = {}

    def process_signal(self, signal, context):
        return []


class FakeMemory:
    def __init__(self):
        self.outcomes = []
        self._effectiveness = {}

    def remember_outcome(self, outcome):
        self.outcomes.append(outcome)

    def get_rule_effectiveness(self, rule_id: str) -> float:
        return self._effectiveness.get(rule_id, 0.5)


class FakeRule:
    def __init__(self):
        self.last_success_rate = 0.5
        self.effectiveness_score = 0.5
        self.priority_boost = 0.0

    def adjust_based_on_outcomes(self):
        self.effectiveness_score = self.last_success_rate


def test_decision_worker_subscribes():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    from shopee_agent.workers import DecisionWorker
    dw = DecisionWorker(bus)
    dw.subscribe()
    assert "decision.signal" in bus._handlers
    assert "cycle.complete" in bus._handlers
    bus.stop()


def test_outcome_worker_subscribes():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    from shopee_agent.workers import OutcomeWorker
    ow = OutcomeWorker(bus)
    ow.subscribe()
    assert "outcome.recorded" in bus._handlers
    assert "cycle.complete" in bus._handlers
    bus.stop()


def test_notification_worker_subscribes():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    from shopee_agent.workers import NotificationWorker
    nw = NotificationWorker(bus)
    nw.subscribe()
    assert "alert" in bus._handlers
    bus.stop()


def test_metric_worker_subscribes():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    from shopee_agent.workers import MetricWorker
    mw = MetricWorker(bus)
    mw.subscribe()
    for t in ("decision.executed", "outcome.recorded", "cycle.complete", "alert"):
        assert t in bus._handlers
    bus.stop()


def test_outcome_worker_records_and_adjusts():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    memory = FakeMemory()
    rule = FakeRule()
    engine = FakeEngine()
    engine.rules["r1"] = rule

    from shopee_agent.workers import OutcomeWorker
    ow = OutcomeWorker(bus, engine=engine, memory_layer=memory)
    ow.subscribe()

    bus.submit(OutcomeRecordedEvent(
        event_type="outcome.recorded", decision_id="d1", rule_id="r1", outcome_type="success"
    ))
    bus.wait_until_idle(timeout=3)
    bus.stop()

    assert len(memory.outcomes) == 1
    assert memory.outcomes[0].decision_id == "d1"


def test_metric_worker_tracks_decisions():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    from shopee_agent.workers import MetricWorker
    mw = MetricWorker(bus)
    mw.subscribe()

    bus.submit(DecisionExecutedEvent(event_type="decision.executed", decision_id="d1", rule_id="r1", status="ok"))
    bus.submit(OutcomeRecordedEvent(event_type="outcome.recorded", decision_id="d1", rule_id="r1", outcome_type="success"))
    bus.submit(CycleCompleteEvent(event_type="cycle.complete", cycle_number=1))
    bus.submit(AlertEvent(event_type="alert", severity="info", title="t", message="m"))
    bus.wait_until_idle(timeout=3)
    bus.stop()

    metrics = mw.get_metrics()
    assert metrics["total_decisions"] == 1
    assert metrics["total_outcomes"] == 1
    assert metrics["success_count"] == 1
    assert metrics["cycles_completed"] == 1
    assert metrics["total_alerts"] == 1


def test_notification_worker_sends_telegram():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    sent = []

    def fake_telegram(text):
        sent.append(text)

    from shopee_agent.workers import NotificationWorker
    nw = NotificationWorker(bus, telegram_sender=fake_telegram)
    nw.subscribe()

    bus.submit(AlertEvent(event_type="alert", severity="warning", title="Low stock", message="Item X is low", tags=["inventory"]))
    bus.wait_until_idle(timeout=3)
    bus.stop()

    assert len(sent) >= 1
    assert "Low stock" in sent[0]
