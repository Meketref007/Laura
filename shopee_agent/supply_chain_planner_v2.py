"""
Phase 41: Advanced supply chain planning v2 — supplier scoring, auto-PO,
multi-warehouse balancing, and procurement optimisation.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .logger import info

# ---------------------------------------------------------------------------
# Helper types
# ---------------------------------------------------------------------------

@dataclass
class SupplierScoreResult:
    supplier_id: str
    overall_score: float
    dimensions: dict[str, float]
    tier: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PO_STATUSES = ("draft", "submitted", "acknowledged", "in_transit", "delivered", "cancelled")


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _tier_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _recommendation_from_tier(tier: str, score: float, dimensions: dict[str, float]) -> str:
    if tier == "A":
        return "Preferred supplier — negotiate volume discounts and long-term contract"
    if tier == "B":
        weak = [k for k, v in dimensions.items() if v < 60]
        if weak:
            return f"Conditionally approved — address weaknesses: {', '.join(weak)}"
        return "Approved for standard orders with quarterly review"
    if tier == "C":
        return "Use only as backup — require performance improvement plan before scaling"
    return "Not recommended — seek alternative suppliers immediately"


# ---------------------------------------------------------------------------
# 1. SupplierScorer
# ---------------------------------------------------------------------------

class SupplierScorer:
    """Evaluates suppliers across multiple dimensions and assigns a tiered score."""

    DEFAULT_WEIGHTS: dict[str, float] = {
        "delivery_time": 0.25,
        "defect_rate": 0.25,
        "price_competitiveness": 0.20,
        "communication_score": 0.10,
        "order_accuracy": 0.20,
    }

    def __init__(self, weights: dict[str, float] | None = None):
        raw = weights or dict(self.DEFAULT_WEIGHTS)
        total = sum(raw.values())
        self.weights = {k: v / total for k, v in raw.items()} if total > 0 else dict(self.DEFAULT_WEIGHTS)

    def score_supplier(self, history: dict) -> dict[str, Any]:
        supplier_id = str(history.get("supplier_id", "unknown"))
        raw = history.get("metrics", history)

        delivery_time = self._score_delivery_time(raw)
        defect_rate = self._score_defect_rate(raw)
        price_competitiveness = self._score_price(raw)
        communication_score = self._score_communication(raw)
        order_accuracy = self._score_order_accuracy(raw)

        dimensions = {
            "delivery_time": delivery_time,
            "defect_rate": defect_rate,
            "price_competitiveness": price_competitiveness,
            "communication_score": communication_score,
            "order_accuracy": order_accuracy,
        }

        overall = sum(dimensions[k] * self.weights[k] for k in self.weights)
        overall = _clamp(overall)
        tier = _tier_from_score(overall)
        recommendation = _recommendation_from_tier(tier, overall, dimensions)

        return SupplierScoreResult(
            supplier_id=supplier_id,
            overall_score=round(overall, 2),
            dimensions=dimensions,
            tier=tier,
            recommendation=recommendation,
        ).to_dict()

    @staticmethod
    def _score_delivery_time(m: dict) -> float:
        avg_late = float(m.get("avg_delivery_late_days", m.get("delivery_time_days", 0)) or 0)
        return _clamp(100 - max(0, avg_late * 12))

    @staticmethod
    def _score_defect_rate(m: dict) -> float:
        rate = float(m.get("defect_rate", m.get("defect_pct", m.get("defect_rate_pct", 0))) or 0)
        return _clamp(100 - rate * 5)

    @staticmethod
    def _score_price(m: dict) -> float:
        if "price_competitiveness" in m:
            pc = float(m["price_competitiveness"] or 1.0)
            idx = 1.0 / max(pc, 0.01)
        else:
            idx = float(m.get("price_index", m.get("cost_multiplier", 1.0)) or 1.0)
        if idx <= 0:
            return 100.0
        return _clamp(100 - (idx - 0.8) * 120)

    @staticmethod
    def _score_communication(m: dict) -> float:
        return _clamp(float(m.get("communication_score", 75) or 75))

    @staticmethod
    def _score_order_accuracy(m: dict) -> float:
        acc = float(m.get("order_accuracy_pct", m.get("order_accuracy", 95)) or 95)
        return _clamp(acc)


# ---------------------------------------------------------------------------
# 2. AutoPurchaseOrderGenerator
# ---------------------------------------------------------------------------

class AutoPurchaseOrderGenerator:
    """Generates, submits, and tracks purchase orders."""

    def __init__(self, storage: dict[str, dict[str, Any]] | None = None):
        self._store: dict[str, dict[str, Any]] = storage if storage is not None else {}

    def generate_po(self, supplier_id: str, items: list, forecast: dict) -> dict:
        if not items:
            return {"error": "No items provided", "po_id": None}

        po_id = f"PO-{uuid.uuid4().hex[:10].upper()}"
        now = datetime.now(UTC).isoformat()

        line_items = []
        total_qty = 0
        estimated_total = 0.0

        demand_factor = max(0.5, min(2.0, float(forecast.get("demand_multiplier", 1.0) or 1.0)))

        for idx, item in enumerate(items, 1):
            item_id = str(item.get("item_id") or item.get("id") or f"item-{idx}")
            name = str(item.get("item_name") or item.get("name") or item_id)
            base_qty = int(item.get("quantity", item.get("qty", 1)) or 1)
            unit_price = float(item.get("unit_price", item.get("price", 0)) or 0)

            adjusted_qty = max(1, int(round(base_qty * demand_factor)))
            total_qty += adjusted_qty
            estimated_total += adjusted_qty * unit_price

            line_items.append({
                "line": idx,
                "item_id": item_id,
                "item_name": name,
                "quantity": adjusted_qty,
                "unit_price": round(unit_price, 2),
                "subtotal": round(adjusted_qty * unit_price, 2),
            })

        po = {
            "po_id": po_id,
            "supplier_id": supplier_id,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "items": line_items,
            "total_quantity": total_qty,
            "estimated_total": round(estimated_total, 2),
            "currency": forecast.get("currency", "USD"),
            "demand_multiplier_applied": round(demand_factor, 4),
            "notes": forecast.get("notes", ""),
        }

        self._store[po_id] = copy.deepcopy(po)
        info("Purchase order generated", po_id=po_id, supplier_id=supplier_id, lines=len(line_items))
        return po

    def submit_po(self, po: dict) -> dict:
        po_id = po.get("po_id")
        if not po_id:
            return {"error": "Missing po_id", "success": False}

        stored = self._store.get(po_id)
        if stored is None:
            return {"error": f"PO {po_id} not found", "success": False}

        if stored["status"] != "draft":
            return {"error": f"PO {po_id} is already {stored['status']}", "success": False}

        stored["status"] = "submitted"
        stored["updated_at"] = datetime.now(UTC).isoformat()
        stored["submission_id"] = f"SUB-{uuid.uuid4().hex[:8]}"
        self._store[po_id] = stored

        info("Purchase order submitted", po_id=po_id)
        return {
            "po_id": po_id,
            "status": "submitted",
            "submission_id": stored["submission_id"],
            "submitted_at": stored["updated_at"],
            "success": True,
        }

    def track_po(self, po_id: str) -> dict:
        po = self._store.get(po_id)
        if po is None:
            return {"error": f"PO {po_id} not found", "po_id": po_id, "status": "unknown"}

        return {
            "po_id": po_id,
            "status": po["status"],
            "supplier_id": po["supplier_id"],
            "created_at": po["created_at"],
            "updated_at": po["updated_at"],
            "total_quantity": po["total_quantity"],
            "estimated_total": po["estimated_total"],
            "tracking_events": self._mock_tracking(po["status"]),
        }

    @staticmethod
    def _mock_tracking(status: str) -> list:
        events = []
        if status in ("submitted", "acknowledged", "in_transit", "delivered"):
            events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Order submitted"})
        if status in ("acknowledged", "in_transit", "delivered"):
            events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Supplier acknowledged"})
        if status in ("in_transit", "delivered"):
            events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Shipped — in transit"})
        if status == "delivered":
            events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Delivered"})
        return events


# ---------------------------------------------------------------------------
# 3. MultiWarehouseBalancer
# ---------------------------------------------------------------------------

class MultiWarehouseBalancer:
    """Suggests inventory transfers across warehouses to match demand."""

    def __init__(self, transfer_cost_per_unit: float = 0.50):
        self.transfer_cost_per_unit = transfer_cost_per_unit

    def balance_inventory(self, warehouses: list[dict], orders: list[dict]) -> list[dict]:
        suggestions: list[dict] = []
        if not warehouses or not orders:
            return suggestions

        demand_by_wh: dict[str, int] = {}
        for order in orders:
            wh = str(order.get("warehouse_id") or order.get("fulfillment_warehouse") or "")
            qty = int(order.get("quantity", 1) or 1)
            demand_by_wh[wh] = demand_by_wh.get(wh, 0) + qty

        wh_stock: dict[str, int] = {}
        for wh in warehouses:
            wid = str(wh.get("warehouse_id") or wh.get("id") or "")
            stock = int(wh.get("stock", wh.get("available_stock", 0)) or 0)
            wh_stock[wid] = stock

        surplus_wh = []
        deficit_wh = []
        for wh_id, stock in wh_stock.items():
            demand = demand_by_wh.get(wh_id, 0)
            if demand > 0:
                ratio = stock / demand if demand else 999
                if ratio > 1.3:
                    surplus_wh.append((wh_id, stock - demand))
                elif ratio < 0.7:
                    deficit_wh.append((wh_id, demand - stock))

        surplus_wh.sort(key=lambda x: -x[1])
        deficit_wh.sort(key=lambda x: -x[1])

        for src_id, excess in surplus_wh:
            remaining = excess
            for dst_id, shortage in deficit_wh:
                if remaining <= 0:
                    break
                transfer = min(remaining, shortage)
                if transfer <= 0:
                    continue
                cost = round(transfer * self.transfer_cost_per_unit, 2)
                suggestions.append({
                    "from_warehouse": src_id,
                    "to_warehouse": dst_id,
                    "sku": "mixed",
                    "transfer_quantity": transfer,
                    "estimated_cost": cost,
                    "reason": f"Re-balance {transfer} units from {src_id} to {dst_id} "
                              f"(surplus {excess} vs deficit {shortage})",
                })
                remaining -= transfer

        return suggestions

    def suggest_rebalance(self, warehouse_id: str, threshold: float = 0.2) -> dict:
        return {
            "warehouse_id": warehouse_id,
            "rebalance_suggested": True,
            "threshold": threshold,
            "strategy": "periodic_audit",
            "action": f"Review stock levels at {warehouse_id} and redistribute "
                      f"if any SKU exceeds +/-{threshold*100:.0f}% of target allocation",
            "estimated_transfer_cost_per_unit": self.transfer_cost_per_unit,
        }


# ---------------------------------------------------------------------------
# 4. SupplyChainPlannerV2
# ---------------------------------------------------------------------------

class SupplyChainPlannerV2:
    """Ties supplier scoring, auto-PO, and multi-warehouse balancing together."""

    def __init__(
        self,
        scorer: SupplierScorer | None = None,
        po_generator: AutoPurchaseOrderGenerator | None = None,
        balancer: MultiWarehouseBalancer | None = None,
    ):
        self.scorer = scorer or SupplierScorer()
        self.po_generator = po_generator or AutoPurchaseOrderGenerator()
        self.balancer = balancer or MultiWarehouseBalancer()

    def analyze_chain(self, context: dict) -> dict:
        plan_id = f"scpv2_{uuid.uuid4().hex[:10]}"

        suppliers_raw = context.get("suppliers", [])
        scored_suppliers = []
        for supplier in suppliers_raw:
            if isinstance(supplier, dict):
                result = self.scorer.score_supplier(supplier)
                scored_suppliers.append(result)

        orders = context.get("orders", context.get("pending_orders", []))
        warehouses = context.get("warehouses", [])
        transfers = self.balancer.balance_inventory(warehouses, orders) if warehouses and orders else []

        risks = self._assess_risks(context, scored_suppliers, transfers)

        return {
            "plan_id": plan_id,
            "analyzed_at": datetime.now(UTC).isoformat(),
            "suppliers_scored": len(scored_suppliers),
            "top_suppliers": self._top_suppliers(scored_suppliers, n=3),
            "warehouse_transfers_suggested": len(transfers),
            "transfers": transfers,
            "risks": risks,
            "supplier_tier_summary": self._tier_summary(scored_suppliers),
        }

    def optimize_procurement(self, forecast: dict, suppliers: list) -> dict:
        if not suppliers:
            return {"error": "No suppliers provided", "recommendations": []}

        scored = [self.scorer.score_supplier(s) for s in suppliers if isinstance(s, dict)]
        scored.sort(key=lambda x: x["overall_score"], reverse=True)

        preferred = [s for s in scored if s["tier"] in ("A", "B")]
        if not preferred:
            preferred = scored[:1]

        demand_mult = max(0.5, min(2.0, float(forecast.get("demand_multiplier", 1.0) or 1.0)))
        total_demand = int(forecast.get("total_demand", forecast.get("forecast_quantity", 0)) or 0)

        allocation_plan = []
        remaining = max(0, total_demand)
        for idx, supplier in enumerate(preferred):
            if remaining <= 0:
                break
            share = 1.0 / max(1, len(preferred))
            if idx == len(preferred) - 1:
                qty = remaining
            else:
                qty = max(0, int(round(total_demand * share * demand_mult)))
                qty = min(qty, remaining)
            qty = max(0, qty)
            remaining -= qty

            items = [{"item_id": forecast.get("item_id", "generic"), "quantity": qty}]

            po = self.po_generator.generate_po(
                supplier_id=supplier["supplier_id"],
                items=items,
                forecast=forecast,
            )

            allocation_plan.append({
                "supplier": supplier,
                "allocated_quantity": qty,
                "purchase_order": po,
            })

        return {
            "forecast_applied": {
                "demand_multiplier": demand_mult,
                "total_demand": total_demand,
            },
            "suppliers_evaluated": len(scored),
            "suppliers_selected": len(preferred),
            "allocation_plan": allocation_plan,
            "unallocated_quantity": max(0, remaining),
        }

    @staticmethod
    def _assess_risks(context: dict, scored_suppliers: list, transfers: list) -> list:
        risks = []

        suppliers_below_c = [s for s in scored_suppliers if s.get("tier") in ("C", "D")]
        if suppliers_below_c:
            risks.append({
                "code": "low_tier_suppliers",
                "severity": "high",
                "message": f"{len(suppliers_below_c)} supplier(s) scored tier C/D",
            })

        if len(transfers) > 5:
            risks.append({
                "code": "excessive_transfers",
                "severity": "medium",
                "message": f"{len(transfers)} suggested transfers indicate systemic imbalance",
            })

        cash = context.get("cash_buffer_usd", context.get("budget", 0))
        if isinstance(cash, (int, float)) and cash < 20000:
            risks.append({
                "code": "tight_cash",
                "severity": "medium",
                "message": f"Cash buffer ${cash:.0f} may constrain procurement",
            })

        return risks

    @staticmethod
    def _top_suppliers(scored: list, n: int = 3) -> list:
        sorted_s = sorted(scored, key=lambda x: x.get("overall_score", 0), reverse=True)
        return sorted_s[:n]

    @staticmethod
    def _tier_summary(scored: list) -> dict[str, int]:
        summary: dict[str, int] = {}
        for s in scored:
            t = s.get("tier", "?")
            summary[t] = summary.get(t, 0) + 1
        return summary
