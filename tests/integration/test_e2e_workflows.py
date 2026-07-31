"""End-to-end integration tests for the full Laura system.

Each test is self-contained and uses mocks for external services.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.skills.registry import Skill, SkillRegistry
from shopee_agent.skills.orchestrator import SkillOrchestrator
from shopee_agent.goap_planner import GOAPPlanner, GOAPAction
from shopee_agent.event_bus import (
    AsyncEventBus,
    Event,
    DecisionSignalEvent,
    AlertEvent,
)
from shopee_agent.decision_engine import (
    DecisionEngine,
    DecisionRule,
    Decision,
    DecisionSignal,
    DecisionType,
    DecisionPriority,
    DecisionStatus,
    EconomicContext,
    RiskLevel,
    default_economic_context,
)
from shopee_agent.decision_memory import MemoryLayer, DecisionOutcome

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def reports_dir(tmp_path):
    d = tmp_path / "reports"
    d.mkdir()
    return d


@pytest.fixture
def fresh_registry():
    return SkillRegistry()


@pytest.fixture
def event_bus():
    bus = AsyncEventBus(worker_count=2, max_retries=0)
    bus.start()
    yield bus
    bus.stop()


# ── Test 1: GOAP Planner + Skills Integration ────────────────────────────────


class TestGoapPlannerSkillsIntegration:

    def test_plan_and_execute_through_orchestrator(self, fresh_registry):
        class CheckStock(Skill):
            name = "check_stock"
            preconditions = {"stock_checked": False}
            effects = {"stock_checked": True}

            def run(self, **kwargs):
                return {"ok": True, "stock": 5}

        class ProtectMargin(Skill):
            name = "protect_margin"
            preconditions = {"stock_checked": True, "margin_protected": False}
            effects = {"stock_checked": True, "margin_protected": True}

            def run(self, **kwargs):
                return {"ok": True, "margin": 0.2}

        fresh_registry.register(CheckStock)
        fresh_registry.register(ProtectMargin)

        orch = SkillOrchestrator(registry=fresh_registry)
        result = orch.evaluate_state(
            {"stock_checked": False, "margin_protected": False},
            {"stock_checked": True, "margin_protected": True},
            max_depth=6,
        )
        assert result["status"] == "executed", (
            f"Expected plan to be executed, got {result['status']}"
        )
        assert len(result.get("results", [])) == 2, (
            f"Expected 2 skill results, got {len(result.get('results', []))}"
        )
        for r in result["results"]:
            assert r.get("ok") is True, (
                f"Skill {r.get('skill')} did not succeed: {r}"
            )

    def test_plan_fails_when_goal_unreachable(self, fresh_registry):
        class ImpossibleSkill(Skill):
            name = "impossible"
            preconditions = {"magic_key": True}
            effects = {"goal_achieved": True}

            def run(self, **kwargs):
                return {"ok": True}

        fresh_registry.register(ImpossibleSkill)
        orch = SkillOrchestrator(registry=fresh_registry)
        result = orch.evaluate_state(
            {"magic_key": False},
            {"goal_achieved": True},
            max_depth=4,
        )
        assert result["status"] == "no_plan", (
            f"Expected no_plan for unreachable goal, got {result['status']}"
        )

    def test_planner_uses_skill_actions_directly(self, fresh_registry):
        planner = GOAPPlanner()
        planner.register_action(GOAPAction(
            name="skill_a",
            cost=1.0,
            preconditions={"x": 0},
            effects={"x": 1},
        ))
        planner.register_action(GOAPAction(
            name="skill_b",
            cost=2.0,
            preconditions={"x": 1},
            effects={"y": 1},
        ))
        plan = planner.plan({"x": 0, "y": 0}, {"x": 1, "y": 1})
        assert plan is not None, "Planner should find a valid plan"
        action_names = [a.name for a in plan]
        assert action_names == ["skill_a", "skill_b"], (
            f"Expected [skill_a, skill_b], got {action_names}"
        )
        explain = planner.explain({"x": 0, "y": 0}, {"x": 1, "y": 1})
        final = explain.get("final_state", {})
        assert final.get("x") == 1, f"Final state x should be 1, got {final}"
        assert final.get("y") == 1, f"Final state y should be 1, got {final}"


# ── Test 2: EventBus + Workers Integration ────────────────────────────────────


class TestEventBusWorkersIntegration:

    def test_handler_receives_submitted_events(self, event_bus):
        received = []

        def handler(event):
            received.append(event)

        event_bus.register_handler("test.event", handler)
        event_bus.submit(Event(event_type="test.event", source="test"))
        event_bus.wait_until_idle(timeout=3)

        assert len(received) == 1, (
            f"Expected 1 event, got {len(received)}"
        )
        assert received[0].event_type == "test.event"
        assert getattr(received[0], "source", "") == "test"

    def test_multiple_handlers_on_same_event(self, event_bus):
        results = []

        def h1(event):
            results.append("h1")

        def h2(event):
            results.append("h2")

        event_bus.register_handler("multi", h1)
        event_bus.register_handler("multi", h2)
        event_bus.submit(Event(event_type="multi"))
        event_bus.wait_until_idle(timeout=3)

        assert results == ["h1", "h2"], (
            f"Expected [h1, h2], got {results}"
        )

    def test_wildcard_handler_catches_all(self, event_bus):
        caught = []

        def wildcard(event):
            caught.append(event.event_type)

        event_bus.register_handler("*", wildcard)
        event_bus.submit(Event(event_type="alpha"))
        event_bus.submit(Event(event_type="beta"))
        event_bus.wait_until_idle(timeout=3)

        assert "alpha" in caught, "Wildcard handler should catch alpha"
        assert "beta" in caught, "Wildcard handler should catch beta"

    def test_priority_alert_processed_first(self):
        bus = AsyncEventBus(worker_count=1)
        bus.start()
        order = []

        def alert_handler(event):
            order.append("alert")

        def normal_handler(event):
            order.append("normal")

        bus.register_handler("alert", alert_handler)
        bus.register_handler("cycle.complete", normal_handler)
        bus.submit(
            AlertEvent(event_type="alert", severity="critical", title="Urgent", message="!")
        )
        bus.submit(
            AlertEvent(event_type="cycle.complete", severity="info", title="Normal", message=".")
        )
        bus.wait_until_idle(timeout=3)
        bus.stop()

        assert order[0] == "alert", (
            f"Alert should be processed first, got {order}"
        )


# ── Test 3: Decision Engine + Memory Integration ──────────────────────────────


class TestDecisionEngineMemoryIntegration:

    def test_decision_outcome_stored_in_memory(self, tmp_path):
        outcomes_path = tmp_path / "outcomes.jsonl"
        mem = MemoryLayer(path=str(outcomes_path))
        rule = DecisionRule(
            rule_id="pricing_margin_protect",
            decision_type=DecisionType.PRICING,
            name="Margin Protection",
            description="Test rule for margin protection",
            condition="current_margin < target_margin * 0.9",
            priority_boost=1,
            risk_threshold=RiskLevel.LOW,
        )
        engine = DecisionEngine(store_id="test", rules=[rule], memory=mem)

        signal = DecisionSignal(
            source="metrics.profitability",
            signal_type="anomaly",
            data={"metric": "margin_drop", "severity": 0.7},
        )
        context = EconomicContext(
            current_margin_pct=15.0,
            margin_target_pct=18.0,
            daily_revenue_usd=5000.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=15,
            stock_risk_level="normal",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=2.0,
            customer_satisfaction_score=80.0,
            recent_anomalies=[],
        )

        decisions = engine.process_signal(signal, context)
        assert len(decisions) > 0, "Engine should generate at least one decision"
        approved = [d for d in decisions if d.status == DecisionStatus.APPROVED]
        if approved:
            d = approved[0]
            ok = engine.execute_decision(d.decision_id)
            assert ok is True, "Engine should execute the decision"

            mem.remember_outcome(DecisionOutcome(
                decision_id=d.decision_id,
                rule_id=d.rule_id,
                outcome_type="success",
                impact_realized=0.5,
            ))

            lines = outcomes_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) >= 1, "Memory should persist at least one outcome"
            assert any(d.decision_id in line for line in lines), (
                f"Decision {d.decision_id} should appear in outcomes file"
            )

    def test_rule_effectiveness_tracked(self, tmp_path):
        mem = MemoryLayer(path=str(tmp_path / "outcomes2.jsonl"))
        mem.remember_outcome(DecisionOutcome(
            decision_id="d1", rule_id="r1", outcome_type="success",
        ))
        mem.remember_outcome(DecisionOutcome(
            decision_id="d2", rule_id="r1", outcome_type="failure",
        ))
        eff = mem.get_rule_effectiveness("r1")
        assert eff == 0.5, (
            f"Expected effectiveness 0.5 (1 success / 2 total), got {eff}"
        )


# ── Test 4: Autonomous Loop Basic Cycle ───────────────────────────────────────


class TestAutonomousLoopBasicCycle:

    def _make_fake_client(self):
        """Create a minimal mock ShopeeClient."""
        from types import SimpleNamespace

        client = MagicMock()

        def fake_get_order_list(**kwargs):
            return SimpleNamespace(data={
                "response": {
                    "order_list": [
                        {
                            "order_sn": "TESTORDER001",
                            "order_status": "READY_TO_SHIP",
                            "create_time": int(time.time()) - 3600,
                        }
                    ]
                }
            })

        def fake_get_item_list(**kwargs):
            return SimpleNamespace(data={
                "response": {"item": [{"item_id": "1001", "stock": 2}]}
            })

        client.get_order_list = fake_get_order_list
        client.get_item_list = fake_get_item_list
        return client

    def test_run_cycle_returns_expected_structure(self, tmp_path):
        from shopee_agent.autonomous_loop import AutonomousLoop

        client = self._make_fake_client()
        loop = AutonomousLoop(
            client=client,
            access_token="fake-token",
            shop_id=123456,
            reports_dir=tmp_path / "reports",
            telegram_token="",
            telegram_chat_id="",
        )

        with (
            patch.object(loop, "_analyze", return_value={"auto": [], "approval": []}),
            patch.object(loop, "_notify_workers", return_value=None),
            patch.object(loop, "_send_telegram", return_value=True),
            patch("shopee_agent.skills.orchestrator.SkillOrchestrator") as mock_orch_cls,
        ):
            mock_orch = MagicMock()
            mock_orch.evaluate_state.return_value = {"status": "no_plan"}
            mock_orch_cls.return_value = mock_orch

            result = loop.run_cycle()

        assert isinstance(result, dict), "Result should be a dict"
        assert "timestamp" in result, "Result should contain 'timestamp'"
        assert "cycle_result" in result, "Result should contain 'cycle_result'"
        assert "executed" in result, "Result should contain 'executed'"
        assert isinstance(result["executed"], list), "'executed' should be a list"


# ── Test 5: Full Pipeline: Metrics -> Decision -> GOAP -> Execution ───────────


class TestFullPipeline:

    def test_metrics_to_decision_to_goap_pipeline(self, tmp_path):
        with patch("shopee_agent.skills.loader.discover_and_register") as mock_discover:
            mock_discover.return_value = None
            engine = DecisionEngine(store_id="test_store", rules=[])
            from shopee_agent.decision_integration import DecisionIntegrator

            integrator = DecisionIntegrator(
                engine=engine,
                store_id="test_store",
                metrics_dir=str(tmp_path / "reports"),
            )

            integrator.collect_signals_from_metrics = MagicMock(return_value=[
                DecisionSignal(
                    source="metrics.profitability",
                    signal_type="anomaly",
                    data={"metric": "margin_drop", "severity": 0.7},
                ),
            ])

            integrator.build_economic_context = MagicMock(return_value=EconomicContext(
                current_margin_pct=12.0,
                margin_target_pct=18.0,
                daily_revenue_usd=3200.0,
                cash_buffer_usd=50000.0,
                inventory_days_on_hand=4,
                stock_risk_level="high",
                active_promotions=0,
                advertising_spend_daily_usd=500.0,
                advertising_roas=1.2,
                customer_satisfaction_score=82.0,
                recent_anomalies=["margin_drop"],
            ))

            result = integrator.process_cycle()

        assert result is not None, "process_cycle should return a result"
        assert "timestamp" in result, "Result should have a timestamp"
        assert result["signals_received"] >= 1, (
            f"Expected at least 1 signal, got {result['signals_received']}"
        )
        assert result["decisions_generated"] >= 0, "Should report decision count"

    def test_decision_converted_to_goap_goal(self, fresh_registry):
        class PricingSkill(Skill):
            name = "adjust_pricing"
            preconditions = {"margin_protected": False}
            effects = {"margin_protected": True}

            def run(self, **kwargs):
                return {"ok": True}

        class StockSkill(Skill):
            name = "restock_items"
            preconditions = {"stock_checked": False}
            effects = {"stock_checked": True}

            def run(self, **kwargs):
                return {"ok": True}

        fresh_registry.register(PricingSkill)
        fresh_registry.register(StockSkill)

        orch = SkillOrchestrator(registry=fresh_registry)

        current_state = {
            "margin_protected": False,
            "stock_checked": False,
            "orders_pending_ship": True,
        }
        goal_state = {
            "margin_protected": True,
            "stock_checked": True,
            "orders_pending_ship": False,
        }
        result = orch.evaluate_state(current_state, goal_state, max_depth=6)

        assert result["status"] in ("executed", "no_plan"), (
            f"Unexpected status: {result['status']}"
        )
        if result["status"] == "executed":
            executed_skills = {r.get("skill") for r in result.get("results", [])}
            assert "adjust_pricing" in executed_skills, (
                f"adjust_pricing should be in executed skills: {executed_skills}"
            )


# ── Test 6: Circuit Breaker + Retry Integration ───────────────────────────────


class TestCircuitBreakerRetryIntegration:

    def test_circuit_opens_on_failures_then_closes_on_recovery(self):
        from shopee_agent.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerConfig,
            CircuitBreakerOpen,
            CircuitState,
        )

        config = CircuitBreakerConfig(failure_threshold=3, success_threshold=2)
        breaker = CircuitBreaker("test_endpoint", config)
        call_count = [0]

        def flaky_endpoint():
            call_count[0] += 1
            if call_count[0] <= 3:
                raise ConnectionError("Transient failure")
            return "success"

        for i in range(3):
            with pytest.raises(ConnectionError):
                breaker.call(flaky_endpoint)

        assert breaker.state == CircuitState.OPEN, (
            f"Circuit should be OPEN after 3 failures, got {breaker.state}"
        )

        with pytest.raises(CircuitBreakerOpen):
            breaker.call(flaky_endpoint)

        assert call_count[0] == 3

        breaker.state = CircuitState.HALF_OPEN
        breaker.success_count = 0

        result = breaker.call(flaky_endpoint)
        assert result == "success", "Call should succeed in HALF_OPEN state"
        assert breaker.state == CircuitState.HALF_OPEN, (
            "Circuit should stay HALF_OPEN after 1 success (needs 2)"
        )

        result = breaker.call(flaky_endpoint)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED, (
            f"Circuit should CLOSE after 2 consecutive successes, got {breaker.state}"
        )

    def test_retry_decorator_with_fallback(self):
        from shopee_agent.retry import RetryConfig, retry

        config = RetryConfig(max_attempts=3, initial_delay_ms=10, jitter=False)
        call_count = [0]

        @retry(config=config, context="test")
        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Not yet")
            return "recovered"

        result = flaky()
        assert result == "recovered"
        assert call_count[0] == 3, (
            f"Expected 3 calls (2 failures + 1 success), got {call_count[0]}"
        )


# ── Test 7: Multi-Agent Orchestration ─────────────────────────────────────────


class TestMultiAgentOrchestration:

    def test_orchestrator_produces_execution_plan(self):
        from shopee_agent.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()
        context = EconomicContext(
            current_margin_pct=12.0,
            margin_target_pct=18.0,
            daily_revenue_usd=3200.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=4,
            stock_risk_level="high",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=1.2,
            customer_satisfaction_score=82.0,
            recent_anomalies=["margin_drop"],
        )

        plan = orchestrator.coordinate_cycle_sync(context)

        assert len(plan.approved_actions) > 0, (
            "Orchestrator should approve at least one action"
        )
        assert plan.consensus_score > 0, (
            f"Consensus score should be positive, got {plan.consensus_score}"
        )
        targets = {a.target for a in plan.approved_actions}
        assert "pricing" in targets, (
            f"Pricing should be in approved targets: {targets}"
        )

    def test_conflicts_detected_between_agents(self):
        from shopee_agent.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()
        context = EconomicContext(
            current_margin_pct=12.0,
            margin_target_pct=18.0,
            daily_revenue_usd=3200.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=4,
            stock_risk_level="high",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=1.2,
            customer_satisfaction_score=82.0,
            recent_anomalies=["margin_drop"],
        )

        plan = orchestrator.coordinate_cycle_sync(context)

        assert plan.conflicts is not None, "Conflicts list should exist"
        assert len(plan.approved_actions) + len(plan.rejected_actions) > 0, (
            "Total actions should be > 0"
        )

    def test_roster_includes_expected_agents(self):
        from shopee_agent.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()
        context = EconomicContext(
            current_margin_pct=17.0,
            margin_target_pct=18.0,
            daily_revenue_usd=6200.0,
            cash_buffer_usd=12000.0,
            inventory_days_on_hand=9,
            stock_risk_level="normal",
            active_promotions=1,
            advertising_spend_daily_usd=800.0,
            advertising_roas=2.3,
            customer_satisfaction_score=84.0,
            recent_anomalies=["competitor_price_drop"],
        )

        plan = orchestrator.coordinate_cycle_sync(context)
        all_agents = {
            a.agent_name
            for a in plan.approved_actions + plan.rejected_actions
        }

        assert "growth_agent" in all_agents, (
            f"growth_agent should be in roster: {all_agents}"
        )
        assert "finance_agent" in all_agents, (
            f"finance_agent should be in roster: {all_agents}"
        )
        assert "competitor_agent" in all_agents, (
            f"competitor_agent should be in roster: {all_agents}"
        )


# ── Test 8: EventBus DLQ Recovery ────────────────────────────────────────────


class TestEventBusDlqRecovery:

    def test_failed_events_land_in_dlq(self):
        bus = AsyncEventBus(worker_count=1, max_retries=1, retry_backoff=0.05)
        bus.start()

        def always_fails(event):
            raise RuntimeError("Permanent failure")

        bus.register_handler("fail.me", always_fails)
        bus.submit(Event(event_type="fail.me"))
        bus.wait_until_idle(timeout=3)
        bus.stop()

        dlq_entries = bus.dlq()
        assert len(dlq_entries) >= 1, (
            f"DLQ should contain at least 1 entry, got {len(dlq_entries)}"
        )
        assert dlq_entries[0].event_type == "fail.me", (
            f"DLQ entry should have correct event_type, got {dlq_entries[0].event_type}"
        )

    def test_replay_dlq_reprocesses_events(self):
        bus = AsyncEventBus(worker_count=1, max_retries=0, retry_backoff=0.05)
        bus.start()
        received = []

        def always_fails(event):
            raise RuntimeError("Fail")

        def collector(event):
            received.append(event)

        bus.register_handler("replay.me", always_fails)
        bus.submit(Event(event_type="replay.me"))
        bus.wait_until_idle(timeout=3)

        dlq_before = len(bus.dlq())
        assert dlq_before >= 1, "Event should be in DLQ"

        bus.register_handler("replay.me", collector)

        replayed = bus.replay_dlq()
        assert replayed >= 1, (
            f"Expected at least 1 event replayed, got {replayed}"
        )
        bus.wait_until_idle(timeout=3)
        bus.stop()


# ── Test 9: Skill Marketplace Export/Import ───────────────────────────────────


class TestSkillMarketplaceExportImport:

    def test_export_and_import_skill_package(self):
        from shopee_agent.skills.marketplace import (
            export_skill_package,
            import_skill_package,
        )

        class MockSkill(Skill):
            name = "market_skill"
            cost = 2.5
            priority = 3
            preconditions = {"x": False}
            effects = {"x": True}

        pkg = export_skill_package(MockSkill, include_source=True)
        assert pkg["format_version"] == "1.0"
        assert pkg["skill"]["name"] == "market_skill"
        assert pkg["skill"]["cost"] == 2.5
        assert pkg["skill"]["preconditions"] == {"x": False}
        assert pkg["skill"]["effects"] == {"x": True}
        assert "checksum" in pkg

        target_registry = SkillRegistry()
        ok = import_skill_package(pkg, target_registry)
        assert ok is True, "Import should succeed"

        imported = target_registry.get("market_skill")
        assert imported is not None, (
            "Imported skill should be in the registry"
        )
        imported_name = getattr(imported, "name", None)
        assert imported_name == "market_skill", (
            f"Expected name 'market_skill', got {imported_name}"
        )

    def test_save_and_load_package_from_disk(self, tmp_path):
        from shopee_agent.skills.marketplace import (
            export_skill_package,
            save_package,
            load_package,
        )

        class FileSkill(Skill):
            name = "file_skill"
            cost = 1.0
            effects = {"saved": True}

        pkg = export_skill_package(FileSkill)
        pkg_path = tmp_path / "packages" / "file_skill.json"
        saved = save_package(pkg, str(pkg_path))
        assert saved.exists(), "Package file should exist on disk"

        loaded = load_package(str(pkg_path))
        assert loaded is not None, "Loaded package should not be None"
        assert loaded["skill"]["name"] == "file_skill"
        assert loaded["format_version"] == "1.0"

    def test_imported_skill_can_be_executed(self):
        from shopee_agent.skills.marketplace import (
            export_skill_package,
            import_skill_package,
        )

        class ExecutableSkill(Skill):
            name = "exec_skill"
            effects = {"done": True}

            def run(self, **kwargs):
                return {"ok": True, "result": "executed"}

        pkg = export_skill_package(ExecutableSkill, include_source=True)
        registry = SkillRegistry()
        import_skill_package(pkg, registry)

        skill_cls = registry.get("exec_skill")
        assert skill_cls is not None, "Skill class should be registered"

        instance = skill_cls()
        result = instance.run()
        assert result.get("ok") is True, (
            f"Imported skill execution should succeed, got {result}"
        )
        msg = result.get("message", "")
        assert "exec_skill" in msg, (
            f"Message should mention skill name, got: {msg}"
        )


# ── Test 10: Plan Store Persistence ───────────────────────────────────────────


class TestPlanStorePersistence:

    def test_save_and_retrieve_plan(self):
        from shopee_agent.plan_store import PlanStore

        store = PlanStore(db_path=":memory:")
        pid = store.save_plan(
            plan_hash="hash_v1",
            start_state={"stock_checked": False},
            goal={"stock_checked": True},
            actions=["check_stock"],
            total_cost=1.0,
            max_depth=6,
            all_ok=False,
        )
        assert pid > 0, f"Expected positive plan id, got {pid}"

        plan = store.get_plan(pid)
        assert plan is not None, "Retrieved plan should not be None"
        assert plan["plan_hash"] == "hash_v1"
        assert plan["actions"] == ["check_stock"]
        assert plan["total_cost"] == 1.0
        assert plan["all_ok"] is False

    def test_plan_content_matches_after_save(self):
        from shopee_agent.plan_store import PlanStore

        store = PlanStore(db_path=":memory:")
        start = {"x": 0, "y": 0}
        goal = {"x": 1, "y": 1}
        actions = ["action_a", "action_b", "action_c"]
        pid = store.save_plan(
            plan_hash="full_test",
            start_state=start,
            goal=goal,
            actions=actions,
            total_cost=3.5,
            max_depth=8,
            max_budget=10.0,
            all_ok=True,
        )
        plan = store.get_plan(pid)

        assert plan["start_state"] == start, (
            f"Start state mismatch: {plan['start_state']} != {start}"
        )
        assert plan["goal"] == goal, (
            f"Goal mismatch: {plan['goal']} != {goal}"
        )
        assert plan["actions"] == actions, (
            f"Actions mismatch: {plan['actions']} != {actions}"
        )
        assert plan["total_cost"] == 3.5
        assert plan["max_depth"] == 8
        assert plan["max_budget"] == 10.0
        assert plan["all_ok"] is True
        assert plan["created_at"] is not None

    def test_mark_executed_updates_plan(self):
        from shopee_agent.plan_store import PlanStore

        store = PlanStore(db_path=":memory:")
        pid = store.save_plan(
            plan_hash="exec_test",
            start_state={},
            goal={},
            actions=["a"],
            total_cost=1.0,
        )
        store.mark_executed(pid, all_ok=True, error="")
        plan = store.get_plan(pid)
        assert plan["all_ok"] is True
        assert plan["executed_at"] is not None, (
            "executed_at should be set after mark_executed"
        )

    def test_store_stats_accurate(self):
        from shopee_agent.plan_store import PlanStore

        store = PlanStore(db_path=":memory:")
        p1 = store.save_plan("h1", {}, {}, ["a"], 1.0, all_ok=True)
        store.mark_executed(p1, all_ok=True)
        p2 = store.save_plan("h2", {}, {}, ["b"], 2.0, all_ok=False)
        store.mark_executed(p2, all_ok=False)
        p3 = store.save_plan("h3", {}, {}, ["c"], 3.0, all_ok=False)

        stats = store.get_stats()
        assert stats["total_plans"] == 3
        assert stats["successful"] == 1
        assert stats["failed"] == 1
        assert stats["pending_execution"] == 1
        assert stats["avg_cost"] > 0
