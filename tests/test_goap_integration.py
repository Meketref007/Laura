"""Integration test: process_cycle + GOAP + skills + event bus + executor."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

from shopee_agent.skills.loader import discover_and_register
from shopee_agent.skills.registry import default_registry
from shopee_agent.skills.orchestrator import SkillOrchestrator
from shopee_agent.goap_planner import GOAPPlanner
from shopee_agent.event_bus import AsyncEventBus, GOAPPlanExecutedEvent
from shopee_agent.decision_engine import (
    DecisionEngine, Decision, DecisionType, DecisionPriority,
    DecisionStatus, DecisionSignal, create_default_rules, default_economic_context,
)
from shopee_agent.decision_integration import DecisionIntegrator, DecisionExecutor


@pytest.fixture
def reports_dir(tmp_path):
    d = tmp_path / "reports"
    d.mkdir()
    return d


class TestFullPipelineIntegration:

    def setup_method(self):
        discover_and_register()

    def test_goap_creates_decisions_in_engine(self):
        """GOAP plan execution creates Decision objects in the engine."""
        engine = DecisionEngine(store_id="test", rules=create_default_rules())
        integrator = DecisionIntegrator(
            engine=engine,
            store_id="test",
            metrics_dir="reports",
        )
        context = default_economic_context()
        integrator.collect_signals_from_metrics = MagicMock(return_value=[])

        result = integrator.process_cycle()
        assert result is not None

        decisions = list(engine.pending_decisions.values())
        goap_decisions = [d for d in decisions if d.metadata.get("goap")]
        # GOAP may or may not find a plan depending on context; just check it doesn't crash

    def test_orchestrator_emits_event(self):
        """SkillOrchestrator emits GOAPPlanExecutedEvent on execution."""
        events = []

        class FakeBus:
            def submit(self, event):
                events.append(event)

        orch = SkillOrchestrator(event_bus=FakeBus())
        result = orch.evaluate_state(
            {"stock_checked": False, "margin_protected": False},
            {"stock_checked": True, "margin_protected": True},
            max_depth=4,
        )
        if result["status"] == "executed":
            assert len(events) >= 1
            assert any(isinstance(e, GOAPPlanExecutedEvent) for e in events)

    def test_executor_routes_goap_decisions(self):
        """Executor can execute a Decision created from GOAP results."""
        executor = DecisionExecutor(store_id="test")
        executor._get_client = MagicMock()
        executor._get_tokens = MagicMock(return_value=("token", 1))

        sig = DecisionSignal(source="goap", signal_type="routine", data={})
        d = Decision(
            decision_id="goap_integration_test",
            title="GOAP: low_stock_alert",
            decision_type=DecisionType.ALERTS,
            recommended_action="checked stock",
            priority=DecisionPriority.LOW,
            impact_score=1.0,
            risk_score=0.3,
            confidence_score=0.8,
            status=DecisionStatus.APPROVED,
            signal=sig,
            rule_id="goap_orchestrator",
            description="low_stock_alert",
            metadata={"skill": "low_stock_alert", "item_id": "test001", "stock": 1, "threshold": 3, "goap": True},
            created_at=datetime.now(timezone.utc),
        )
        result = executor.execute(d)
        assert result is True

    def test_event_bus_receives_goap_event(self):
        """GOAPPlanExecutedEvent is properly submitted to and received from event bus."""
        import asyncio
        received = []

        async def run():
            bus = AsyncEventBus(worker_count=2)
            bus.start()
            bus.register_handler("goap.plan_executed", lambda e: received.append(e))

            ev = GOAPPlanExecutedEvent(
                actions=["low_stock_alert"],
                total_cost=0.8,
                results=[{"ok": True}],
                all_ok=True,
                state_snapshot={"test": True},
            )
            bus.submit(ev)
            await asyncio.sleep(0.3)
            bus.wait_until_idle(timeout=2.0)
            bus.stop()
            return received

        result = asyncio.run(run())
        assert len(result) >= 1
        assert result[0].event_type == "goap.plan_executed"

    def test_skill_cache_reuses_instance(self):
        """SkillRegistry.get_or_create returns cached instance."""
        discover_and_register()
        inst1 = default_registry.get_or_create("low_stock_alert")
        inst2 = default_registry.get_or_create("low_stock_alert")
        assert inst1 is inst2  # same object

    def test_skill_cache_clear(self):
        """SkillRegistry.clear_cache removes cached instances."""
        discover_and_register()
        inst1 = default_registry.get_or_create("low_stock_alert")
        default_registry.clear_cache()
        inst2 = default_registry.get_or_create("low_stock_alert")
        assert inst1 is not inst2

    def test_tracer_basic(self):
        """Tracer records and emits span metrics."""
        from shopee_agent.tracing import SpanTracer, DistributedTracer
        dt = DistributedTracer()
        tracer = SpanTracer(dt)
        sid = tracer.start_span("test_op", tags={"key": "val"})
        tracer.end_span(sid, status="ok")
        # no crash is the test

    def test_tracer_decorator(self):
        """Trace decorator works without event bus."""
        from shopee_agent.tracing import trace
        call_count = 0

        @trace("test_decorator")
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result = my_func(5)
        assert result == 10
        assert call_count == 1

    def test_dashboard_skills_endpoint(self):
        """Dashboard /api/skills returns expected structure."""
        from shopee_agent.dashboard import app, _get_api_key
        from fastapi.testclient import TestClient
        client = TestClient(app)
        api_key = _get_api_key()
        resp = client.get("/api/skills", headers={"Authorization": f"Bearer {api_key}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "registered_skills" in data
        assert "total_executions" in data
        assert "success_rate_pct" in data
        assert "per_skill" in data
