from __future__ import annotations

import time
from datetime import datetime, timezone

from shopee_agent.event_bus import (
    AsyncEventBus,
    Event,
    DecisionSignalEvent,
    DecisionExecutedEvent,
    OutcomeRecordedEvent,
    CycleCompleteEvent,
    AlertEvent,
    MetricUpdateEvent,
)


def test_event_base_has_timestamp():
    e = Event(event_type="test")
    assert e.event_type == "test"
    assert e.timestamp is not None
    assert isinstance(e.timestamp, datetime)


def test_typed_events():
    dse = DecisionSignalEvent(event_type="decision.signal", source="test", signal="sig", context="ctx")
    assert dse.signal == "sig"
    assert dse.context == "ctx"

    dee = DecisionExecutedEvent(event_type="decision.executed", decision_id="d1", rule_id="r1", status="success")
    assert dee.decision_id == "d1"
    assert dee.rule_id == "r1"

    ore = OutcomeRecordedEvent(event_type="outcome.recorded", decision_id="d1", rule_id="r1", outcome_type="success")
    assert ore.outcome_type == "success"

    cce = CycleCompleteEvent(event_type="cycle.complete", cycle_number=5, summary={"orders": 10})
    assert cce.cycle_number == 5
    assert cce.summary["orders"] == 10

    ae = AlertEvent(event_type="alert", severity="error", title="Test", message="msg")
    assert ae.severity == "error"
    assert ae.title == "Test"

    mue = MetricUpdateEvent(event_type="metric.update", metrics={"a": 1})
    assert mue.metrics["a"] == 1


def test_bus_start_stop():
    bus = AsyncEventBus(worker_count=2)
    bus.start()
    assert bus._running
    bus.stop()
    assert not bus._running


def test_bus_submit_and_dispatch():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    received = []

    def handler(event):
        received.append(event)

    bus.register_handler("ping", handler)
    bus.submit(Event(event_type="ping"))
    bus.wait_until_idle(timeout=3)
    bus.stop()

    assert len(received) == 1
    assert received[0].event_type == "ping"


def test_bus_sync_fallback():
    bus = AsyncEventBus(worker_count=1)
    received = []

    def handler(event):
        received.append(event)

    bus.register_handler("sync-test", handler)
    bus.submit(Event(event_type="sync-test"))
    assert len(received) == 1  # dispatched synchronously


def test_bus_stats():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    def ok_handler(event):
        pass

    bus.register_handler("ok", ok_handler)
    bus.submit(Event(event_type="ok"))
    bus.wait_until_idle(timeout=3)
    stats = bus.stats()
    assert stats.queued >= 0
    bus.stop()


def test_wildcard_handler():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    wildcard_received = []

    def wildcard(event):
        wildcard_received.append(event)

    bus.register_handler("*", wildcard)
    bus.submit(Event(event_type="any.event"))
    bus.wait_until_idle(timeout=3)
    bus.stop()

    assert len(wildcard_received) == 1


def test_multiple_handlers_same_type():
    bus = AsyncEventBus(worker_count=1)
    bus.start()

    results = []

    def h1(event):
        results.append("h1")

    def h2(event):
        results.append("h2")

    bus.register_handler("multi", h1)
    bus.register_handler("multi", h2)
    bus.submit(Event(event_type="multi"))
    bus.wait_until_idle(timeout=3)
    bus.stop()

    assert results == ["h1", "h2"]
