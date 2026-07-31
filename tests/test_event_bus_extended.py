from __future__ import annotations

import json
import tempfile
from pathlib import Path

from shopee_agent.event_bus import AsyncEventBus, AlertEvent, MetricUpdateEvent, DeadLetterEvent


def test_bus_retry_then_dlq():
    """Handler that always fails should retry then land in DLQ."""
    import time
    bus = AsyncEventBus(worker_count=1, max_retries=2, retry_backoff=0.05)
    bus.start()

    calls = []

    def failing_handler(event):
        calls.append(1)
        raise ValueError("always fail")

    bus.register_handler("alert", failing_handler)
    bus.submit(AlertEvent(severity="error", title="failme"))

    for _ in range(50):
        if bus.stats().failed > 0:
            break
        time.sleep(0.1)

    bus.stop()

    # 1 initial attempt + 2 retries = 3 calls
    assert len(calls) == 3, f"expected 3 calls, got {len(calls)}"
    assert len(bus.dlq()) == 1, f"expected 1 DLQ entry, got {len(bus.dlq())}"
    dl = bus.dlq()[0]
    assert "always fail" in dl.error


def test_bus_dlq_replay():
    import time
    bus = AsyncEventBus(worker_count=1, max_retries=1, retry_backoff=0.05)
    bus.start()

    call_count = 0

    def always_fail(event):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fail")

    bus.register_handler("alert", always_fail)
    bus.submit(AlertEvent(severity="error", title="replay_me"))

    for _ in range(50):
        if bus.stats().failed > 0:
            break
        time.sleep(0.1)

    assert bus.stats().failed == 1, f"expected 1 failed, stats={bus.stats()}"
    assert len(bus.dlq()) == 1
    first_dlq = bus.dlq()[0]
    assert "always fail" in first_dlq.error

    replayed = bus.replay_dlq()
    assert replayed == 1

    for _ in range(50):
        if bus.stats().failed >= 2:
            break
        time.sleep(0.1)

    assert bus.stats().failed >= 2, f"expected failed>=2 after replay, stats={bus.stats()}"
    bus.stop()


def test_bus_journal_writes(tmp_path):
    journal = tmp_path / "events.jsonl"
    bus = AsyncEventBus(worker_count=1, journal_path=str(journal))
    bus.start()

    bus.submit(AlertEvent(severity="info", title="journal_test"))

    def collector(event):
        pass

    bus.register_handler("alert", collector)
    bus.submit(AlertEvent(severity="info", title="journal_test2"))
    bus.wait_until_idle(timeout=5)
    bus.stop()

    assert journal.exists()
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    for line in lines:
        obj = json.loads(line)
        assert "ts" in obj
        assert "event_type" in obj


def test_bus_journal_continue_across_restart(tmp_path):
    """Append to the same journal across stop/start."""
    journal = tmp_path / "events_cont.jsonl"
    bus = AsyncEventBus(worker_count=1, journal_path=str(journal))
    bus.start()
    bus.submit(AlertEvent(severity="info", title="a"))
    bus.wait_until_idle(timeout=5)
    bus.stop()

    bus2 = AsyncEventBus(worker_count=1, journal_path=str(journal))
    bus2.start()
    bus2.submit(AlertEvent(severity="info", title="b"))
    bus2.wait_until_idle(timeout=5)
    bus2.stop()

    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, f"expected 2 events, got {len(lines)}"


def test_metric_update_event_default_type():
    """MetricUpdateEvent should have event_type='metric.update'."""
    e = MetricUpdateEvent(metrics={"foo": 1})
    assert e.event_type == "metric.update"


def test_bus_sync_dispatch_dlq():
    """When bus not running, sync dispatch should also use DLQ on failure."""
    bus = AsyncEventBus(worker_count=1)
    calls = []

    def fail_handler(event):
        calls.append(1)
        raise ValueError("sync fail")

    bus.register_handler("alert", fail_handler)
    bus.submit(AlertEvent(severity="error", title="sync_dlq"))

    assert len(calls) == 1
    assert len(bus.dlq()) >= 1
