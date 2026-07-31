from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shopee_agent.supply_chain_planner_v2 import (
    SupplierScorer,
    AutoPurchaseOrderGenerator,
    MultiWarehouseBalancer,
    SupplyChainPlannerV2,
    SupplierScoreResult,
    _tier_from_score,
    _clamp,
)


class TestSupplierScorer:
    @pytest.fixture
    def scorer(self):
        return SupplierScorer()

    def test_score_perfect_supplier(self, scorer):
        history = {
            "supplier_id": "SUP-001",
            "avg_delivery_late_days": 0,
            "defect_rate": 0,
            "price_competitiveness": 1.25,
            "communication_score": 100,
            "order_accuracy_pct": 100,
        }
        result = scorer.score_supplier(history)
        assert result["tier"] == "A"
        assert result["overall_score"] >= 85

    def test_score_poor_supplier(self, scorer):
        history = {
            "supplier_id": "SUP-002",
            "avg_delivery_late_days": 10,
            "defect_rate": 20,
            "price_index": 2.0,
            "communication_score": 20,
            "order_accuracy_pct": 30,
        }
        result = scorer.score_supplier(history)
        assert result["tier"] in ("C", "D")
        assert result["overall_score"] < 70

    def test_score_supplier_missing_fields(self, scorer):
        history = {"supplier_id": "SUP-003"}
        result = scorer.score_supplier(history)
        assert "supplier_id" in result
        assert result["overall_score"] >= 0

    def test_score_supplier_with_nested_metrics(self, scorer):
        history = {"supplier_id": "SUP-004", "metrics": {"delivery_time_days": 2, "defect_pct": 1, "price_index": 1.0}}
        result = scorer.score_supplier(history)
        assert result["overall_score"] > 0

    def test_custom_weights(self):
        custom = SupplierScorer(weights={"delivery_time": 1.0, "defect_rate": 0.0, "price_competitiveness": 0.0, "communication_score": 0.0, "order_accuracy": 0.0})
        history = {"supplier_id": "SUP-005", "avg_delivery_late_days": 0, "defect_rate": 10, "price_index": 1.5, "communication_score": 50}
        result = custom.score_supplier(history)
        assert result["overall_score"] == 100.0

    def test_different_supplier_scores(self, scorer):
        suppliers = [
            {"supplier_id": "S1", "avg_delivery_late_days": 0, "defect_rate": 0, "price_competitiveness": 1.25, "communication_score": 95, "order_accuracy_pct": 99},
            {"supplier_id": "S2", "avg_delivery_late_days": 5, "defect_rate": 5, "price_index": 1.2, "communication_score": 60, "order_accuracy_pct": 80},
            {"supplier_id": "S3", "avg_delivery_late_days": 15, "defect_rate": 15, "price_index": 1.8, "communication_score": 30, "order_accuracy_pct": 50},
        ]
        scores = [scorer.score_supplier(s) for s in suppliers]
        assert scores[0]["overall_score"] > scores[1]["overall_score"] > scores[2]["overall_score"]
        assert scores[0]["tier"] == "A"
        assert scores[2]["tier"] in ("C", "D")


class TestAutoPurchaseOrderGenerator:
    @pytest.fixture
    def generator(self):
        return AutoPurchaseOrderGenerator()

    def test_generate_po(self, generator):
        items = [{"item_id": "ITM-1", "item_name": "Widget", "quantity": 100, "unit_price": 5.0}]
        forecast = {"demand_multiplier": 1.2, "currency": "USD"}
        po = generator.generate_po("SUP-001", items, forecast)
        assert po["po_id"].startswith("PO-")
        assert po["status"] == "draft"
        assert po["total_quantity"] == 120
        assert po["estimated_total"] == 600.0

    def test_generate_po_no_items(self, generator):
        result = generator.generate_po("SUP-001", [], {})
        assert "error" in result
        assert result["po_id"] is None

    def test_submit_po(self, generator):
        items = [{"item_id": "ITM-1", "quantity": 10, "unit_price": 2.0}]
        po = generator.generate_po("SUP-001", items, {})
        result = generator.submit_po(po)
        assert result["success"] is True
        assert result["status"] == "submitted"

    def test_submit_po_not_found(self, generator):
        result = generator.submit_po({"po_id": "PO-NONEXIST"})
        assert result["success"] is False

    def test_track_po(self, generator):
        items = [{"item_id": "ITM-1", "quantity": 10, "unit_price": 2.0}]
        po = generator.generate_po("SUP-001", items, {})
        tracker = generator.track_po(po["po_id"])
        assert tracker["status"] == "draft"
        assert tracker["supplier_id"] == "SUP-001"

    def test_track_po_not_found(self, generator):
        tracker = generator.track_po("PO-MISSING")
        assert tracker["status"] == "unknown"

    def test_auto_purchase_order_generator(self, generator):
        items = [{"item_id": "ITM-A", "item_name": "Alpha", "quantity": 50, "unit_price": 10.0}]
        forecast = {"demand_multiplier": 1.5, "notes": "Urgent restock", "currency": "BRL"}
        po = generator.generate_po("SUP-010", items, forecast)
        assert po["total_quantity"] == 75
        assert po["estimated_total"] == 750.0
        assert po["demand_multiplier_applied"] == 1.5
        assert po["currency"] == "BRL"


class TestMultiWarehouseBalancer:
    @pytest.fixture
    def balancer(self):
        return MultiWarehouseBalancer(transfer_cost_per_unit=0.50)

    def test_balance_inventory(self, balancer):
        warehouses = [
            {"warehouse_id": "WH-1", "stock": 100},
            {"warehouse_id": "WH-2", "stock": 10},
        ]
        orders = [
            {"warehouse_id": "WH-1", "quantity": 20},
            {"warehouse_id": "WH-2", "quantity": 50},
        ]
        suggestions = balancer.balance_inventory(warehouses, orders)
        assert len(suggestions) > 0
        assert suggestions[0]["from_warehouse"] == "WH-1"
        assert suggestions[0]["to_warehouse"] == "WH-2"

    def test_balance_inventory_no_transfer_needed(self, balancer):
        warehouses = [{"warehouse_id": "WH-1", "stock": 30}, {"warehouse_id": "WH-2", "stock": 30}]
        orders = [{"warehouse_id": "WH-1", "quantity": 25}, {"warehouse_id": "WH-2", "quantity": 25}]
        assert balancer.balance_inventory(warehouses, orders) == []

    def test_balance_inventory_empty(self, balancer):
        assert balancer.balance_inventory([], []) == []
        assert balancer.balance_inventory([], [{"qty": 1}]) == []
        assert balancer.balance_inventory([{"id": "WH-1", "stock": 10}], []) == []

    def test_multi_warehouse_balancer_suggest_rebalance(self, balancer):
        result = balancer.suggest_rebalance("WH-001")
        assert result["warehouse_id"] == "WH-001"
        assert result["rebalance_suggested"] is True
        assert result["strategy"] == "periodic_audit"


class TestSupplyChainPlannerV2:
    @pytest.fixture
    def planner(self):
        return SupplyChainPlannerV2()

    def test_analyze_chain(self, planner):
        context = {
            "suppliers": [
                {"supplier_id": "S1", "avg_delivery_late_days": 0, "defect_rate": 0, "price_competitiveness": 1.25, "communication_score": 100, "order_accuracy_pct": 100},
                {"supplier_id": "S2", "avg_delivery_late_days": 8, "defect_rate": 10, "price_index": 1.5, "communication_score": 40, "order_accuracy_pct": 60},
            ],
            "warehouses": [{"warehouse_id": "WH-1", "stock": 50}, {"warehouse_id": "WH-2", "stock": 5}],
            "orders": [{"warehouse_id": "WH-2", "quantity": 20}],
            "cash_buffer_usd": 10000,
        }
        result = planner.analyze_chain(context)
        assert result["suppliers_scored"] == 2
        assert len(result["top_suppliers"]) == 2
        assert result["supplier_tier_summary"]["A"] == 1

    def test_optimize_procurement(self, planner):
        forecast = {"item_id": "ITM-X", "total_demand": 1000, "demand_multiplier": 1.0}
        suppliers = [
            {"supplier_id": "S1", "avg_delivery_late_days": 0, "defect_rate": 0, "price_competitiveness": 1.25, "communication_score": 100, "order_accuracy_pct": 100},
        ]
        result = planner.optimize_procurement(forecast, suppliers)
        assert "allocation_plan" in result
        assert result["suppliers_evaluated"] == 1
        assert result["unallocated_quantity"] == 0

    def test_optimize_procurement_no_suppliers(self, planner):
        result = planner.optimize_procurement({}, [])
        assert "error" in result

    def test_supply_chain_planner_v2_full_flow(self, planner):
        context = {
            "suppliers": [
                {"supplier_id": "S-A", "avg_delivery_late_days": 0, "defect_rate": 0, "price_competitiveness": 1.25, "communication_score": 100, "order_accuracy_pct": 100},
                {"supplier_id": "S-B", "avg_delivery_late_days": 3, "defect_rate": 2, "price_index": 1.1, "communication_score": 75, "order_accuracy_pct": 90},
            ],
            "warehouses": [{"warehouse_id": "WH-1", "stock": 200}, {"warehouse_id": "WH-2", "stock": 20}],
            "orders": [{"warehouse_id": "WH-2", "quantity": 100}],
            "cash_buffer_usd": 5000,
            "budget": 5000,
        }
        result = planner.analyze_chain(context)
        assert len(result["risks"]) >= 1
        assert any(r["code"] == "tight_cash" for r in result["risks"])


class TestHelpers:
    def test_clamp(self):
        assert _clamp(150, 0, 100) == 100
        assert _clamp(-10, 0, 100) == 0
        assert _clamp(50, 0, 100) == 50

    def test_tier_from_score(self):
        assert _tier_from_score(90) == "A"
        assert _tier_from_score(75) == "B"
        assert _tier_from_score(60) == "C"
        assert _tier_from_score(40) == "D"
