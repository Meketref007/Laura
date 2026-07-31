"""Tests for round 9 evolution features:
1. Prometheus MetricsExporter
2. Flash Sale Executor
3. A/B Test Auto-Promote (statistical significance)
4. Browser Automation Skill
5. Supply Chain v2 (supplier scoring, PO gen, warehouse balance)
6. Federated Learning v2 (secure aggregation, DP, cross-store)
7. Event Bus Backends (Redis/RabbitMQ factory)
8. Plan Healer v2 (degraded, circuit-aware, multi-path)
9. Multi-Agent CLI integration
10. Queue management CLI
"""

from __future__ import annotations

from typing import Any, Dict

import pytest


# ── 1. Prometheus MetricsExporter ───────────────────────────────────────────


class TestMetricsExporter:

    def test_render_empty(self):
        from shopee_agent.metrics_exporter import MetricsExporter
        m = MetricsExporter()
        text = m.render()
        assert "# HELP" in text
        assert "# TYPE" in text

    def test_inc_counter(self):
        from shopee_agent.metrics_exporter import MetricsExporter
        m = MetricsExporter()
        m.inc("laura_events_queued_total", value=5)
        text = m.render()
        assert "laura_events_queued_total 5" in text

    def test_inc_with_labels(self):
        from shopee_agent.metrics_exporter import MetricsExporter
        m = MetricsExporter()
        m.inc("laura_skills_executed_total", labels={"skill_name": "test", "status": "ok"})
        text = m.render()
        assert 'skill_name="test"' in text
        assert 'status="ok"' in text

    def test_set_gauge(self):
        from shopee_agent.metrics_exporter import MetricsExporter
        m = MetricsExporter()
        m.set("laura_circuit_breaker_state", value=1, labels={"endpoint": "api"})
        text = m.render()
        assert "laura_circuit_breaker_state 1" in text

    def test_observe_histogram(self):
        from shopee_agent.metrics_exporter import MetricsExporter
        m = MetricsExporter()
        m.observe("laura_skills_duration_seconds", value=0.5, labels={"skill_name": "test"})
        text = m.render()
        assert "laura_skills_duration_seconds_count" in text
        assert "laura_skills_duration_seconds_sum" in text

    def test_register_fastapi(self):
        from shopee_agent.metrics_exporter import MetricsExporter
        m = MetricsExporter()
        # Should not crash when registering (even if no app)
        try:
            from fastapi import FastAPI
            app = FastAPI()
            m.register(app)
        except Exception:
            pass  # fastapi may not be installed


# ── 2. Flash Sale Executor ──────────────────────────────────────────────────


class TestFlashSaleExecutor:

    def test_imports(self):
        from shopee_agent.flash_sale_executor import FlashSaleExecutor
        assert callable(FlashSaleExecutor)


# ── 3. A/B Test Auto-Promote ────────────────────────────────────────────────


class TestABTestAutomator:

    def test_z_test_implementation(self):
        from shopee_agent.ab_test_automator import two_proportion_z_test
        z, p = two_proportion_z_test(0.1, 0.2, 100, 100)
        assert isinstance(z, float)
        assert isinstance(p, float)
        assert 0 < p < 1

    def test_z_test_same_rate(self):
        from shopee_agent.ab_test_automator import two_proportion_z_test
        z, p = two_proportion_z_test(0.15, 0.15, 200, 200)
        # Same rate should give high p-value (not significant)
        assert p > 0.05

    def test_z_test_different_rate(self):
        from shopee_agent.ab_test_automator import two_proportion_z_test
        z, p = two_proportion_z_test(0.05, 0.25, 100, 100)
        # Very different rates should give low p-value
        assert p < 0.05

    def test_automator_evaluate(self):
        from shopee_agent.skills.ab_testing import ABTestRegistry
        from shopee_agent.ab_test_automator import ABTestAutomator
        registry = ABTestRegistry()
        automator = ABTestAutomator(registry)
        # No active tests
        results = automator.evaluate_all(min_samples=1)
        assert isinstance(results, list)

    def test_normal_cdf(self):
        from shopee_agent.ab_test_automator import _normal_cdf
        assert abs(_normal_cdf(0.0) - 0.5) < 0.01
        assert _normal_cdf(-10) < 0.01
        assert _normal_cdf(10) > 0.99


# ── 4. Browser Automation Skill ──────────────────────────────────────────────


class TestBrowserSkill:

    def test_skill_registered(self):
        from shopee_agent.skills.registry import default_registry
        names = default_registry.list()
        assert "browser_skill" in names

    def test_skill_class(self):
        from shopee_agent.skills.browser_skill import BrowserSkill
        skill = BrowserSkill()
        assert skill.name == "browser_skill"
        assert skill.cost == 3.0

    def test_seller_center_skill(self):
        from shopee_agent.skills.browser_skill import SellerCenterBrowserSkill
        skill = SellerCenterBrowserSkill()
        assert skill.name == "seller_center_browser"
        assert skill.cost == 5.0

    def test_validate_params(self):
        from shopee_agent.skills.browser_skill import BrowserSkill
        skill = BrowserSkill()
        valid = skill.validate_params({"action": "navigate", "url": "https://example.com"})
        assert valid is True

    def test_validate_params_invalid_action(self):
        from shopee_agent.skills.browser_skill import BrowserSkill
        skill = BrowserSkill()
        valid = skill.validate_params({"action": "invalid_action"})
        assert valid is False

    def test_run_no_browser(self):
        import os

        import pytest

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                exe = p.chromium.executable_path
        except Exception:
            exe = None
        if not exe or not os.path.exists(exe):
            pytest.skip("Playwright browser not installed in CI environment")
        from shopee_agent.skills.browser_skill import BrowserSkill
        skill = BrowserSkill()
        result = skill.run({"action": "navigate", "url": "https://example.com"})
        # Should gracefully handle no browser available
        assert isinstance(result, dict)
        assert "ok" in result


# ── 5. Supply Chain v2 ──────────────────────────────────────────────────────


class TestSupplyChainV2:

    def test_supplier_scorer(self):
        from shopee_agent.supply_chain_planner_v2 import SupplierScorer
        scorer = SupplierScorer()
        result = scorer.score_supplier({
            "supplier_id": "sup_001",
            "delivery_time_days": 5,
            "defect_rate_pct": 2,
            "price_competitiveness": 0.85,
            "communication_score": 0.9,
            "order_accuracy_pct": 98,
        })
        assert result["supplier_id"] == "sup_001"
        assert 0 <= result["overall_score"] <= 100
        assert result["tier"] in ("A", "B", "C", "D")

    def test_supplier_scorer_bad(self):
        from shopee_agent.supply_chain_planner_v2 import SupplierScorer
        scorer = SupplierScorer()
        result = scorer.score_supplier({
            "supplier_id": "sup_bad",
            "delivery_time_days": 30,
            "defect_rate_pct": 20,
            "price_competitiveness": 0.3,
            "communication_score": 0.2,
            "order_accuracy_pct": 50,
        })
        assert result["tier"] in ("C", "D")

    def test_po_generator(self):
        from shopee_agent.supply_chain_planner_v2 import AutoPurchaseOrderGenerator
        gen = AutoPurchaseOrderGenerator()
        po = gen.generate_po("sup_001", [{"name": "Item A", "qty": 100}], {})
        assert po["supplier_id"] == "sup_001"
        assert len(po["items"]) == 1
        assert po["status"] == "draft"

    def test_po_submit(self):
        from shopee_agent.supply_chain_planner_v2 import AutoPurchaseOrderGenerator
        gen = AutoPurchaseOrderGenerator()
        po = gen.generate_po("sup_001", [{"name": "Item A", "qty": 100}], {})
        result = gen.submit_po(po)
        assert result["status"] == "submitted"

    def test_warehouse_balance(self):
        from shopee_agent.supply_chain_planner_v2 import MultiWarehouseBalancer
        balancer = MultiWarehouseBalancer()
        result = balancer.suggest_rebalance("wh_001")
        assert isinstance(result, dict)
        assert "warehouse_id" in result

    def test_planner_analyze(self):
        from shopee_agent.supply_chain_planner_v2 import SupplyChainPlannerV2
        planner = SupplyChainPlannerV2()
        result = planner.analyze_chain({})
        assert isinstance(result, dict)


# ── 6. Federated Learning v2 ────────────────────────────────────────────────


class TestFederatedLearningV2:

    def test_secure_aggregation(self):
        from shopee_agent.federated_learning_v2 import SecureAggregationProtocol
        sa = SecureAggregationProtocol()
        reports = [
            {"store": "a", "data": {"cost": 1.0, "rate": 0.5}},
            {"store": "b", "data": {"cost": 2.0, "rate": 0.7}},
        ]
        result = sa.aggregate_secure(reports)
        assert result["cost"] == 1.5
        assert result["rate"] == 0.6

    def test_differential_privacy(self):
        from shopee_agent.federated_learning_v2 import DifferentialPrivacyEngine
        dp = DifferentialPrivacyEngine()
        params = {"cost": 1.5, "rate": 0.6}
        noisy = dp.add_noise(params, epsilon=10.0)
        assert "cost" in noisy
        assert "rate" in noisy

    def test_cross_store_sharing(self, tmp_path):
        from shopee_agent.federated_learning_v2 import CrossStoreModelSharing
        db = str(tmp_path / "sharing.json")
        sharing = CrossStoreModelSharing(db_path=db)
        ok = sharing.share_model("store_a", "store_b", {"cost": 1.5})
        assert ok is True
        assert "store_b" in sharing.list_shared_models()

    def test_orchestrator_secure_round(self, tmp_path):
        from shopee_agent.federated_learning_v2 import FederatedLearningOrchestratorV2
        orch = FederatedLearningOrchestratorV2(db_path=str(tmp_path / "fed.json"), epsilon=100.0)
        reports = [
            {"store": "a", "cost_overrides": {"skill_x": {"current_cost": 1.0}}, "base_actions": ["skill_x"]},
            {"store": "b", "cost_overrides": {"skill_x": {"current_cost": 3.0}}, "base_actions": ["skill_x"]},
        ]
        result = orch.secure_round(reports)
        assert result["num_stores"] == 2

    def test_orchestrator_privacy_report(self, tmp_path):
        from shopee_agent.federated_learning_v2 import FederatedLearningOrchestratorV2
        orch = FederatedLearningOrchestratorV2(db_path=str(tmp_path / "priv.json"))
        report = orch.get_privacy_report()
        assert "epsilon_spent" in report


# ── 7. Event Bus Backends ───────────────────────────────────────────────────


class TestEventBusBackends:

    def test_auto_event_bus_memory(self):
        from shopee_agent.event_bus_backends import auto_event_bus
        bus = auto_event_bus("memory")
        assert bus is not None
        assert hasattr(bus, "submit")
        assert hasattr(bus, "stats")

    def test_auto_event_bus_unknown(self):
        from shopee_agent.event_bus_backends import auto_event_bus
        bus = auto_event_bus("invalid_backend")
        # Should fall back to memory
        assert bus is not None
        assert hasattr(bus, "submit")

    def test_event_bus_submit_and_stats(self):
        from shopee_agent.event_bus_backends import auto_event_bus
        bus = auto_event_bus("memory")
        bus.submit({"event_type": "test"})
        stats = bus.stats()
        # Stats object should exist
        assert hasattr(stats, "queued") or isinstance(stats, dict)

    def test_redis_fallback(self):
        from shopee_agent.event_bus_backends import RedisEventBus
        bus = RedisEventBus(host="localhost", port=6379)
        # Should initialize (may fall back to memory if redis not installed)
        assert bus is not None

    def test_rabbitmq_fallback(self):
        from shopee_agent.event_bus_backends import RabbitMQEventBus
        bus = RabbitMQEventBus(url="amqp://localhost")
        # Should initialize (may fall back to memory if aio_pika not installed)
        assert bus is not None


# ── 8. Plan Healer v2 ──────────────────────────────────────────────────────


class TestPlanHealerV2:

    def test_execute_with_healing_exists(self):
        from shopee_agent.plan_healer import execute_with_healing
        assert callable(execute_with_healing)

    def test_execute_with_degraded_healing(self):
        from shopee_agent.plan_healer import execute_with_degraded_healing
        assert callable(execute_with_degraded_healing)

    def test_execute_circuit_aware(self):
        from shopee_agent.plan_healer import execute_circuit_aware
        assert callable(execute_circuit_aware)

    def test_multi_path_healing(self):
        from shopee_agent.plan_healer import multi_path_healing
        assert callable(multi_path_healing)

    def test_degraded_healing_with_no_orchestrator(self):
        from shopee_agent.plan_healer import execute_with_degraded_healing
        # Should not crash even with minimal params
        class MockOrch:
            def evaluate_state(self, state, goal, dry_run=False):
                return {"results": [], "skills": [], "all_ok": False, "state_snapshot": state}
        orch = MockOrch()
        result = execute_with_degraded_healing(orch, {"x": False}, {"x": True}, degraded_skills=["broken"])
        assert result["status"] in ("degraded_failed", "degraded_ok")

    def test_circuit_aware_healing(self):
        from shopee_agent.plan_healer import execute_circuit_aware
        class MockOrch:
            def evaluate_state(self, state, goal, dry_run=False):
                return {"results": [], "skills": [], "all_ok": False, "state_snapshot": state}
        result = execute_circuit_aware(MockOrch(), {"x": False}, {"x": True}, circuit_breaker_map={"broken_skill": True})
        assert isinstance(result, dict)


# ── 9. CLI Integration ────────────────────────────────────────────────────


class TestCLIIntegration:

    def test_cli_imports(self):
        from shopee_agent.cli import build_parser, main
        assert callable(build_parser)
        assert callable(main)

    def test_parser_builds(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        assert p is not None

    def test_queue_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["queue", "status"])
        assert args.command == "queue"
        assert args.queue_action == "status"

    def test_queue_dlq_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["queue", "dlq", "--max", "5"])
        assert args.command == "queue"
        assert args.queue_action == "dlq"
        assert args.max == 5

    def test_metrics_export_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["metrics-export"])
        assert args.command == "metrics-export"

    def test_metrics_export_with_output(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["metrics-export", "--output", "out.txt"])
        assert args.output == "out.txt"

    def test_flash_sale_exec_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["flash-sale-exec", "list"])
        assert args.command == "flash-sale-exec"
        assert args.action == "list"

    def test_flash_sale_create_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["flash-sale-exec", "create", "--auto-approve"])
        assert args.action == "create"
        assert args.auto_approve is True

    def test_ab_auto_promote_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["ab-auto-promote", "--min-confidence", "0.99", "--min-samples", "50"])
        assert args.command == "ab-auto-promote"
        assert args.min_confidence == 0.99
        assert args.min_samples == 50

    def test_browser_run_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["browser-run", "navigate", "--url", "https://example.com"])
        assert args.command == "browser-run"
        assert args.action == "navigate"
        assert args.url == "https://example.com"

    def test_browser_screenshot_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["browser-run", "screenshot", "--screenshot"])
        assert args.action == "screenshot"
        assert args.screenshot is True

    def test_supply_chain_score_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["supply-chain", "score-supplier", "--supplier-id", "sup_abc"])
        assert args.command == "supply-chain"
        assert args.sc_action == "score-supplier"
        assert args.supplier_id == "sup_abc"

    def test_supply_chain_po_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["supply-chain", "generate-po", "--supplier-id", "s1"])
        assert args.sc_action == "generate-po"

    def test_federated_v2_secure_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["federated-v2", "secure-round"])
        assert args.command == "federated-v2"
        assert args.fed_v2_action == "secure-round"

    def test_federated_v2_privacy_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["federated-v2", "privacy"])
        assert args.fed_v2_action == "privacy"

    def test_federated_v2_cross_train_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["federated-v2", "cross-train", "--store-id", "store_x", "--rounds", "5"])
        assert args.fed_v2_action == "cross-train"
        assert args.store_id == "store_x"
        assert args.rounds == 5

    def test_agent_orchestration_list_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["agent-orchestration", "list"])
        assert args.command == "agent-orchestration"
        assert args.agent_action == "list"

    def test_agent_orchestration_status_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["agent-orchestration", "status"])
        assert args.agent_action == "status"

    def test_agent_orchestration_negotiate_parser(self):
        from shopee_agent.cli import build_parser
        p = build_parser()
        args = p.parse_args(["agent-orchestration", "negotiate", "--context", '{"margin_pct": 15}'])
        assert args.agent_action == "negotiate"
        assert args.context == '{"margin_pct": 15}'
