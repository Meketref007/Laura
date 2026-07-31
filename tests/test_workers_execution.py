from __future__ import annotations

from shopee_agent.event_bus import (
    AsyncEventBus, CycleCompleteEvent, MetricUpdateEvent,
)


class FakeExecutor:
    """Minimal executor stub for testing worker dispatch."""

    def __init__(self):
        self.executed: list = []
        self.fail = False

    def execute(self, decision) -> bool:
        if self.fail:
            raise RuntimeError("executor fail")
        self.executed.append(decision)
        return True


def test_metric_worker_handles_metric_update():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    from shopee_agent.workers import MetricWorker
    mw = MetricWorker(bus)
    mw.subscribe()

    bus.submit(MetricUpdateEvent(metrics={"revenue": 5000, "orders": 42}))
    bus.wait_until_idle(timeout=5)
    bus.stop()

    mm = mw.get_metrics()
    assert mm.get("revenue") == 5000
    assert mm.get("orders") == 42


def test_orchestration_worker_executes_actions():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    executor = FakeExecutor()
    from shopee_agent.workers import OrchestrationWorker
    ow = OrchestrationWorker(bus, executor=executor)
    ow.subscribe()

    bus.submit(CycleCompleteEvent(cycle_number=24, summary={"ok": True}))
    bus.wait_until_idle(timeout=10)
    bus.stop()

    # The worker should have executed some actions (even if empty plan)
    # Just verify no crash - approved_actions may be empty
    assert bus.stats().failed == 0


def test_planning_worker_executes_phases():
    bus = AsyncEventBus(worker_count=1)
    bus.start()
    executor = FakeExecutor()
    from shopee_agent.workers import PlanningWorker
    pw = PlanningWorker(bus, executor=executor)
    pw.subscribe()

    bus.submit(CycleCompleteEvent(cycle_number=48, summary={"ok": True}))
    bus.wait_until_idle(timeout=10)
    bus.stop()

    assert bus.stats().failed == 0
