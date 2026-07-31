from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import PROFITABILITY_HISTORY, PROFITABILITY_LATEST


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _metric_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("metrics"), dict):
        return dict(payload["metrics"])
    return dict(payload)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


@dataclass
class ProfitSnapshot:
    revenue: float = 0.0
    cogs: float = 0.0
    ad_spend: float = 0.0
    shipping_subsidy: float = 0.0
    refunds: float = 0.0
    orders: int = 0
    profit: float = 0.0
    margin_pct: float = 0.0
    roas: float | None = None
    refund_rate_pct: float = 0.0
    source_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastPoint:
    period: int
    revenue: float
    profit: float
    margin_pct: float
    confidence: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EconomicScenario:
    name: str
    revenue: float
    profit: float
    margin_pct: float
    roas: float | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EconomicBrainSnapshot:
    generated_at: str
    current: ProfitSnapshot
    history_points: int
    revenue_trend_pct: float
    profit_trend_pct: float
    margin_delta_pct: float
    forecasts: list[ForecastPoint]
    scenarios: list[EconomicScenario]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "current": self.current.to_dict(),
            "history_points": self.history_points,
            "revenue_trend_pct": self.revenue_trend_pct,
            "profit_trend_pct": self.profit_trend_pct,
            "margin_delta_pct": self.margin_delta_pct,
            "forecasts": [forecast.to_dict() for forecast in self.forecasts],
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "recommendations": list(self.recommendations),
        }


class EconomicBrain:
    """Small profit/forecast/simulation layer for Phase 4."""

    def __init__(
        self,
        latest_path: str = str(PROFITABILITY_LATEST),
        history_path: str = str(PROFITABILITY_HISTORY),
        lookback: int = 7,
    ):
        self.latest_path = Path(latest_path)
        self.history_path = Path(history_path)
        self.lookback = max(1, int(lookback))

    def load_latest_snapshot(self) -> ProfitSnapshot:
        current = self._load_latest_metrics()
        return self._snapshot_from_metrics(current)

    def load_history(self, limit: int | None = None) -> list[ProfitSnapshot]:
        if not self.history_path.exists():
            return []

        snapshots: list[ProfitSnapshot] = []
        with self.history_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                metrics = _metric_bundle(payload)
                snapshots.append(self._snapshot_from_metrics(metrics, timestamp=str(payload.get("timestamp") or payload.get("recorded_at") or "")))

        if limit is None:
            return snapshots
        return snapshots[-limit:]

    def analyze(self) -> EconomicBrainSnapshot:
        current = self.load_latest_snapshot()
        history = self.load_history(limit=self.lookback)
        historical_series = history if history else [current]

        revenue_trend_pct = self._trend_pct([point.revenue for point in historical_series])
        profit_trend_pct = self._trend_pct([point.profit for point in historical_series])
        margin_delta_pct = (historical_series[-1].margin_pct - historical_series[0].margin_pct) if len(historical_series) >= 2 else 0.0

        forecasts = self._forecast_series(historical_series, periods=3)
        scenarios = self._simulate_scenarios(current)
        recommendations = self._recommendations(current, forecasts, scenarios)

        return EconomicBrainSnapshot(
            generated_at=_utc_now().isoformat(),
            current=current,
            history_points=len(historical_series),
            revenue_trend_pct=revenue_trend_pct,
            profit_trend_pct=profit_trend_pct,
            margin_delta_pct=margin_delta_pct,
            forecasts=forecasts,
            scenarios=scenarios,
            recommendations=recommendations,
        )

    def forecast_profit(self, periods: int = 3) -> list[ForecastPoint]:
        history = self.load_history(limit=self.lookback)
        if not history:
            history = [self.load_latest_snapshot()]
        return self._forecast_series(history, periods=max(1, periods))

    def simulate(self, scenario_name: str) -> EconomicScenario:
        scenario_map = {scenario.name: scenario for scenario in self._simulate_scenarios(self.load_latest_snapshot())}
        if scenario_name in scenario_map:
            return scenario_map[scenario_name]
        raise KeyError(f"Unknown scenario: {scenario_name}")

    def snapshot(self) -> dict[str, Any]:
        return self.analyze().to_dict()

    def _load_latest_metrics(self) -> dict[str, Any]:
        if self.latest_path.exists():
            try:
                payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
                return _metric_bundle(payload)
            except Exception:
                pass

        history = self.load_history(limit=1)
        if history:
            return history[-1].to_dict()

        return {}

    def _snapshot_from_metrics(self, metrics: dict[str, Any], timestamp: str | None = None) -> ProfitSnapshot:
        revenue = _float(metrics.get("revenue") or metrics.get("daily_revenue_usd"))
        cogs = _float(metrics.get("cogs"))
        ad_spend = _float(metrics.get("ad_spend") or metrics.get("advertising_spend_daily_usd"))
        shipping_subsidy = _float(metrics.get("shipping_subsidy") or metrics.get("shipping"))
        refunds = _float(metrics.get("refunds"))
        orders = int(_float(metrics.get("orders"), 0.0))
        profit = _float(metrics.get("profit"), revenue - cogs - ad_spend - shipping_subsidy - refunds)
        margin_pct = _float(metrics.get("margin_pct"), (profit / revenue * 100.0) if revenue else 0.0)
        roas_raw = metrics.get("roas")
        roas = None if roas_raw is None else _float(roas_raw, 0.0)
        refund_rate_pct = _float(metrics.get("refund_rate_pct"), (refunds / revenue * 100.0) if revenue else 0.0)
        return ProfitSnapshot(
            revenue=revenue,
            cogs=cogs,
            ad_spend=ad_spend,
            shipping_subsidy=shipping_subsidy,
            refunds=refunds,
            orders=orders,
            profit=profit,
            margin_pct=margin_pct,
            roas=roas,
            refund_rate_pct=refund_rate_pct,
            source_timestamp=timestamp,
        )

    def _trend_pct(self, values: list[float]) -> float:
        if len(values) < 2 or values[0] == 0:
            return 0.0
        return ((values[-1] - values[0]) / abs(values[0])) * 100.0

    def _forecast_series(self, history: list[ProfitSnapshot], periods: int) -> list[ForecastPoint]:
        latest = history[-1]
        previous = history[-2] if len(history) >= 2 else latest
        revenue_delta = latest.revenue - previous.revenue
        profit_delta = latest.profit - previous.profit
        margin_delta = latest.margin_pct - previous.margin_pct

        forecasts: list[ForecastPoint] = []
        current_revenue = latest.revenue
        current_profit = latest.profit
        current_margin = latest.margin_pct
        for period in range(1, periods + 1):
            current_revenue = max(0.0, current_revenue + revenue_delta)
            current_profit = current_profit + profit_delta
            current_margin = max(0.0, current_margin + margin_delta)
            confidence = max(0.35, 0.9 - (period - 1) * 0.15)
            forecasts.append(
                ForecastPoint(
                    period=period,
                    revenue=round(current_revenue, 2),
                    profit=round(current_profit, 2),
                    margin_pct=round(current_margin, 2),
                    confidence=round(confidence, 2),
                    notes=["linear trend extrapolation"],
                )
            )
        return forecasts

    def _simulate_scenarios(self, current: ProfitSnapshot) -> list[EconomicScenario]:
        scenarios: list[EconomicScenario] = []

        price_up_revenue = current.revenue * 0.97 if current.revenue else 0.0
        price_up_profit = current.profit + (current.revenue * 0.025)
        price_up_margin = (price_up_profit / price_up_revenue * 100.0) if price_up_revenue else current.margin_pct
        scenarios.append(
            EconomicScenario(
                name="price_up_5pct",
                revenue=round(price_up_revenue, 2),
                profit=round(price_up_profit, 2),
                margin_pct=round(price_up_margin, 2),
                roas=current.roas,
                notes=["assumes modest demand softness and better margin capture"],
            )
        )

        ad_cut_revenue = current.revenue * 0.97 if current.revenue else 0.0
        ad_cut_profit = current.profit + (current.ad_spend * 0.15)
        ad_cut_margin = (ad_cut_profit / ad_cut_revenue * 100.0) if ad_cut_revenue else current.margin_pct
        ad_cut_roas = (ad_cut_revenue / max(1.0, current.ad_spend * 0.85)) if current.ad_spend else current.roas
        scenarios.append(
            EconomicScenario(
                name="ad_cut_15pct",
                revenue=round(ad_cut_revenue, 2),
                profit=round(ad_cut_profit, 2),
                margin_pct=round(ad_cut_margin, 2),
                roas=round(ad_cut_roas, 2) if ad_cut_roas is not None else None,
                notes=["assumes lower spend with some revenue compression"],
            )
        )

        growth_revenue = current.revenue * 1.08 if current.revenue else 0.0
        growth_profit = current.profit + (current.revenue * 0.03) - (current.ad_spend * 0.10)
        growth_margin = (growth_profit / growth_revenue * 100.0) if growth_revenue else current.margin_pct
        growth_roas = (growth_revenue / max(1.0, current.ad_spend * 1.10)) if current.ad_spend else current.roas
        scenarios.append(
            EconomicScenario(
                name="growth_push",
                revenue=round(growth_revenue, 2),
                profit=round(growth_profit, 2),
                margin_pct=round(growth_margin, 2),
                roas=round(growth_roas, 2) if growth_roas is not None else None,
                notes=["assumes controlled growth with modest ad reinvestment"],
            )
        )

        return scenarios

    def _recommendations(
        self,
        current: ProfitSnapshot,
        forecasts: list[ForecastPoint],
        scenarios: list[EconomicScenario],
    ) -> list[str]:
        recommendations: list[str] = []

        if current.revenue <= 0:
            recommendations.append("Collect fresh revenue inputs before taking financial action.")
        if current.margin_pct < 20.0:
            recommendations.append("Protect margin: review pricing, COGS and subsidies.")
        if current.roas is not None and current.roas < 1.8:
            recommendations.append("Reduce wasted ad spend and reallocate budget to better-performing campaigns.")
        if current.refund_rate_pct >= 5.0:
            recommendations.append("Investigate refunds and consider product/content fixes before scaling.")
        if forecasts and forecasts[0].profit < current.profit:
            recommendations.append("Forecast points to declining profit; run a conservative scenario first.")

        best = max(scenarios, key=lambda scenario: scenario.profit, default=None)
        if best is not None and best.name == "growth_push" and best.profit >= current.profit:
            recommendations.append("Growth push appears viable if guardrails remain healthy.")

        if not recommendations:
            recommendations.append("Economic profile is stable; continue monitoring and validating assumptions.")

        return list(dict.fromkeys(recommendations))
