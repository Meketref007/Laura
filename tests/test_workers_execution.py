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


def test_orchestration_worker_builds_valid_decision():
    """Regression: Decision.__init__ requires many mandatory args (rule_id,
    recommended_action, impact_score, risk_score, confidence_score, signal).
    OrchestrationWorker must build a well-formed Decision for the executor."""
    from types import SimpleNamespace

    from shopee_agent.decision_engine import Decision, DecisionType, DecisionStatus
    from shopee_agent.workers import OrchestrationWorker

    bus = AsyncEventBus(worker_count=1)
    bus.start()
    executor = FakeExecutor()
    ow = OrchestrationWorker(bus, executor=executor)

    action = SimpleNamespace(
        action_id="act_1",
        agent_name="pricing",
        action_type="price_change",
        target="item_123",
        direction="up",
        magnitude=5,
        rationale="raise 5% to protect margin",
        priority=4,
    )
    assert ow._execute_action(action) is True
    bus.stop()

    assert len(executor.executed) == 1
    dec = executor.executed[0]
    assert isinstance(dec, Decision)
    assert dec.decision_type == DecisionType.PRICING
    assert dec.status == DecisionStatus.APPROVED
    assert dec.rule_id == "orchestration_worker"
    assert dec.recommended_action
    assert dec.signal is not None
    assert dec.metadata["source"] == "orchestration_worker"


def test_orchestration_worker_handles_executor_failure():
    from types import SimpleNamespace

    from shopee_agent.workers import OrchestrationWorker

    bus = AsyncEventBus(worker_count=1)
    bus.start()
    executor = FakeExecutor()
    executor.fail = True
    ow = OrchestrationWorker(bus, executor=executor)

    action = SimpleNamespace(
        action_id="act-2",
        agent_name="ads",
        action_type="increase_ad_budget",
        target="ad_campaign_1",
        direction="up",
        magnitude=10,
        rationale="boost campaign",
        priority=2,
    )
    assert ow._execute_action(action) is False
    bus.stop()
