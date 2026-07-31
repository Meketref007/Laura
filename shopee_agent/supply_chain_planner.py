"""
Phase 40: Supply chain planning for procurement and logistics.

Reads the inventory monitor snapshot and produces procurement and logistics
recommendations with a small deterministic strategy layer.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .decision_engine import EconomicContext
from .logger import info, warning
from .predictive_analytics import PredictiveAnalytics


@dataclass
class SupplierProfile:
    name: str
    lead_time_days: int
    cost_multiplier: float
    reliability_score: float
    shipping_mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcurementRecommendation:
    item_id: str
    item_name: str
    current_stock: int
    target_cover_days: int
    reorder_quantity: int
    urgency: str
    preferred_supplier: str
    negotiation_hint: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LogisticsRecommendation:
    shipping_mode: str
    consolidation: str
    priority: str
    risk_level: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupplyChainRisk:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupplyChainPlan:
    plan_id: str
    generated_at: str
    horizon_days: int
    inventory_snapshot_path: str
    low_stock_count: int
    procurement_recommendations: list[ProcurementRecommendation] = field(default_factory=list)
    logistics_recommendations: list[LogisticsRecommendation] = field(default_factory=list)
    risks: list[SupplyChainRisk] = field(default_factory=list)
    supplier_profiles: list[SupplierProfile] = field(default_factory=list)
    forecast_snapshot: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "generated_at": self.generated_at,
            "horizon_days": self.horizon_days,
            "inventory_snapshot_path": self.inventory_snapshot_path,
            "low_stock_count": self.low_stock_count,
            "procurement_recommendations": [item.to_dict() for item in self.procurement_recommendations],
            "logistics_recommendations": [item.to_dict() for item in self.logistics_recommendations],
            "risks": [risk.to_dict() for risk in self.risks],
            "supplier_profiles": [profile.to_dict() for profile in self.supplier_profiles],
            "forecast_snapshot": self.forecast_snapshot,
        }


class SupplyChainPlanner:
    """Generates procurement and logistics recommendations from inventory data."""

    def __init__(
        self,
        reports_dir: str = "reports",
        predictive_analytics: PredictiveAnalytics | None = None,
        target_cover_days: int = 21,
    ):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.predictive_analytics = predictive_analytics
        self.target_cover_days = target_cover_days
        self.supplier_profiles = [
            SupplierProfile("local_fast_supplier", lead_time_days=2, cost_multiplier=1.08, reliability_score=0.97, shipping_mode="express"),
            SupplierProfile("regional_balanced_supplier", lead_time_days=5, cost_multiplier=1.00, reliability_score=0.92, shipping_mode="standard"),
            SupplierProfile("low_cost_supplier", lead_time_days=9, cost_multiplier=0.92, reliability_score=0.84, shipping_mode="economy"),
        ]

    def plan_supply_chain(self, horizon_days: int = 14) -> SupplyChainPlan:
        snapshot_path, inventory = self._load_inventory_snapshot()
        low_stock_items = inventory.get("low_stock_items", []) if isinstance(inventory, dict) else []
        low_stock_count = int(inventory.get("low_stock_count", len(low_stock_items))) if isinstance(inventory, dict) else len(low_stock_items)

        forecast_snapshot = None
        if self.predictive_analytics is not None:
            try:
                forecast_snapshot = self.predictive_analytics.forecast_overview(horizon_days=horizon_days).to_dict()
            except Exception as exc:
                warning("Failed to obtain predictive snapshot for supply chain", error=str(exc))

        recommendations: list[ProcurementRecommendation] = []
        logistics: list[LogisticsRecommendation] = []
        risks: list[SupplyChainRisk] = []

        growth_bias = self._growth_bias(forecast_snapshot)

        for item in low_stock_items:
            if not isinstance(item, dict):
                continue

            item_id = str(item.get("item_id") or item.get("id") or "")
            item_name = str(item.get("item_name") or item.get("name") or f"item-{item_id}")
            stock = self._safe_int(item.get("stock", 0))
            threshold = max(1, self._safe_int(item.get("threshold", 5)))

            target_stock = int(math.ceil(self.target_cover_days * growth_bias))
            reorder_quantity = max(target_stock - stock, threshold * 2)

            supplier = self._choose_supplier(stock=stock, reorder_quantity=reorder_quantity)
            urgency = self._urgency(stock, supplier)
            recommendations.append(
                ProcurementRecommendation(
                    item_id=item_id,
                    item_name=item_name,
                    current_stock=stock,
                    target_cover_days=self.target_cover_days,
                    reorder_quantity=reorder_quantity,
                    urgency=urgency,
                    preferred_supplier=supplier.name,
                    negotiation_hint=self._negotiation_hint(supplier, urgency),
                    reason=self._reason_for_reorder(stock, threshold, supplier, growth_bias),
                )
            )

            logistics.append(
                LogisticsRecommendation(
                    shipping_mode=supplier.shipping_mode,
                    consolidation="split_shipment" if stock <= threshold else "batch_consolidation",
                    priority=urgency,
                    risk_level=self._risk_level(stock, supplier),
                    reason=f"{item_name} should use {supplier.shipping_mode} shipping with {supplier.name}.",
                )
            )

        if low_stock_count > 0:
            risks.append(SupplyChainRisk(code="stockout_risk", severity="high", message=f"{low_stock_count} item(s) below threshold"))

        if forecast_snapshot:
            high_risk_metrics = forecast_snapshot.get("high_risk_metrics", [])
            if any(metric in {"margin", "roas"} for metric in high_risk_metrics):
                risks.append(SupplyChainRisk(code="cost_pressure", severity="medium", message="Forecasts suggest tighter margin control"))
            if "inventory_days:high" in forecast_snapshot.get("signals", []):
                risks.append(SupplyChainRisk(code="replenishment_pressure", severity="high", message="Inventory days forecast is deteriorating"))

        plan = SupplyChainPlan(
            plan_id=f"scp_{uuid.uuid4().hex[:10]}",
            generated_at=datetime.now(UTC).isoformat(),
            horizon_days=horizon_days,
            inventory_snapshot_path=str(snapshot_path),
            low_stock_count=low_stock_count,
            procurement_recommendations=recommendations,
            logistics_recommendations=logistics,
            risks=risks,
            supplier_profiles=self.supplier_profiles,
            forecast_snapshot=forecast_snapshot,
        )

        info(
            "Supply chain plan generated",
            plan_id=plan.plan_id,
            low_stock_count=low_stock_count,
            recommendations=len(recommendations),
        )
        return plan

    def assess_supply_chain_risk(self, plan: SupplyChainPlan) -> dict[str, Any]:
        critical = [risk for risk in plan.risks if risk.severity == "high"]
        return {
            "plan_id": plan.plan_id,
            "risk_count": len(plan.risks),
            "critical_risk_count": len(critical),
            "risk_codes": [risk.code for risk in plan.risks],
            "status": "at_risk" if critical else "watch",
        }

    def adapt_supply_chain_plan(self, plan: SupplyChainPlan, context: EconomicContext) -> SupplyChainPlan:
        if context.cash_buffer_usd < 20000:
            for recommendation in plan.procurement_recommendations:
                recommendation.urgency = "medium" if recommendation.urgency == "high" else recommendation.urgency
                recommendation.negotiation_hint = "Prioritize payment terms over fastest delivery"

        if context.inventory_days_on_hand <= 7:
            for logistics in plan.logistics_recommendations:
                logistics.priority = "high"
                logistics.risk_level = "high"

        return plan

    def _load_inventory_snapshot(self) -> tuple[Path, dict[str, Any]]:
        latest_path = self.reports_dir / "laura_inventory_monitor_latest.json"
        if latest_path.exists():
            try:
                return latest_path, json.loads(latest_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        candidates = sorted(self.reports_dir.glob("store_health_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for candidate in candidates:
            try:
                report = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            inventory = report.get("sections", {}).get("inventory", {}) if isinstance(report, dict) else {}
            if inventory:
                return candidate, inventory

        return latest_path, {}

    def _growth_bias(self, forecast_snapshot: dict[str, Any] | None) -> float:
        if not forecast_snapshot:
            return 1.0

        bias = 1.0
        for forecast in forecast_snapshot.get("forecasts", []):
            if not isinstance(forecast, dict):
                continue
            metric = forecast.get("metric")
            direction = forecast.get("direction")
            risk_level = forecast.get("risk_level")
            if metric == "revenue" and direction == "increasing":
                bias += 0.1
            if metric == "revenue" and direction == "decreasing":
                bias -= 0.1
            if metric == "inventory_days" and risk_level == "high":
                bias += 0.2

        return max(0.8, min(1.4, bias))

    def _choose_supplier(self, stock: int, reorder_quantity: int) -> SupplierProfile:
        if stock <= 3 or reorder_quantity >= 25:
            return self.supplier_profiles[0]
        if reorder_quantity >= 10:
            return self.supplier_profiles[1]
        return self.supplier_profiles[2]

    def _urgency(self, stock: int, supplier: SupplierProfile) -> str:
        if stock <= 3 or supplier.lead_time_days <= 2:
            return "high"
        if stock <= 7:
            return "medium"
        return "low"

    def _risk_level(self, stock: int, supplier: SupplierProfile) -> str:
        if stock <= 3 or supplier.reliability_score < 0.9:
            return "high"
        if supplier.lead_time_days > 7:
            return "medium"
        return "low"

    def _negotiation_hint(self, supplier: SupplierProfile, urgency: str) -> str:
        if urgency == "high":
            return f"Negotiate expedited terms with {supplier.name} while preserving fill rate"
        if supplier.cost_multiplier > 1.0:
            return f"Trade volume commitment for lower cost with {supplier.name}"
        return f"Seek better payment terms with {supplier.name}"

    def _reason_for_reorder(self, stock: int, threshold: int, supplier: SupplierProfile, growth_bias: float) -> str:
        if stock <= threshold:
            return f"Stock is at or below threshold and growth bias is {growth_bias:.2f}; reorder now"
        return f"Buffer replenishment recommended via {supplier.name} due to forecasted demand"

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0
