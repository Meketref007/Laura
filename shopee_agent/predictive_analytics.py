"""
Phase 39: Predictive analytics and advanced integrations.

Provides lightweight forecasts over existing Laura history files so planning
and orchestration layers can make forward-looking decisions without requiring
heavy external ML dependencies.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .logger import info


@dataclass
class ForecastSeries:
    metric: str
    points: list[float] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    horizon_days: int = 7
    method: str = "linear_trend"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastResult:
    metric: str
    current_value: float
    forecast_value: float
    trend_per_day: float
    confidence: float
    direction: str
    risk_level: str
    recommendation: str
    samples: int
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PredictiveSnapshot:
    generated_at: str
    horizon_days: int
    forecasts: list[ForecastResult]
    risks: list[str]
    signals: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "horizon_days": self.horizon_days,
            "forecasts": [forecast.to_dict() for forecast in self.forecasts],
            "risks": list(self.risks),
            "signals": list(self.signals),
        }


class PredictiveAnalytics:
    """Small deterministic forecaster built on local history files."""

    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def forecast_overview(self, horizon_days: int = 7) -> PredictiveSnapshot:
        forecasts: list[ForecastResult] = []
        signals: list[str] = []

        for forecast in [
            self.forecast_revenue(horizon_days=horizon_days),
            self.forecast_margin(horizon_days=horizon_days),
            self.forecast_roas(horizon_days=horizon_days),
            self.forecast_inventory_days(horizon_days=horizon_days),
        ]:
            if forecast is None:
                continue
            forecasts.append(forecast)
            if forecast.risk_level in {"high", "critical"}:
                signals.append(f"{forecast.metric}:{forecast.risk_level}")

        risks = self._derive_risks(forecasts)
        info("Predictive snapshot generated", horizon_days=horizon_days, forecasts=len(forecasts))
        return PredictiveSnapshot(
            generated_at=datetime.now(UTC).isoformat(),
            horizon_days=horizon_days,
            forecasts=forecasts,
            risks=risks,
            signals=signals,
        )

    def forecast_revenue(self, horizon_days: int = 7) -> ForecastResult | None:
        series = self._load_profitability_series("daily_revenue_usd", fallback_key="gross_revenue_usd")
        return self._forecast_series(
            metric="revenue",
            series=series,
            horizon_days=horizon_days,
            recommendation_template=(
                "Scale demand if revenue is rising" if series and len(series) >= 2 else "Insufficient revenue history"
            ),
        )

    def forecast_margin(self, horizon_days: int = 7) -> ForecastResult | None:
        series = self._load_profitability_series("gross_margin_pct", fallback_key="margin_pct")
        return self._forecast_series(
            metric="margin",
            series=series,
            horizon_days=horizon_days,
            recommendation_template="Protect margin if forecast falls below target",
        )

    def forecast_roas(self, horizon_days: int = 7) -> ForecastResult | None:
        series = self._load_profitability_series("actual_roas", fallback_key="roas")
        return self._forecast_series(
            metric="roas",
            series=series,
            horizon_days=horizon_days,
            recommendation_template="Reallocate budget if ROAS weakens",
        )

    def forecast_inventory_days(self, horizon_days: int = 7) -> ForecastResult | None:
        series = self._load_state_series("inventory_doh", fallback_key="inventory_days_on_hand")
        return self._forecast_series(
            metric="inventory_days",
            series=series,
            horizon_days=horizon_days,
            recommendation_template="Replenish inventory if cover is declining",
        )

    def predict_risk_summary(self, horizon_days: int = 7) -> dict[str, Any]:
        snapshot = self.forecast_overview(horizon_days=horizon_days)
        high_risk = [forecast.metric for forecast in snapshot.forecasts if forecast.risk_level in {"high", "critical"}]
        return {
            "generated_at": snapshot.generated_at,
            "horizon_days": horizon_days,
            "high_risk_metrics": high_risk,
            "signals": snapshot.signals,
            "forecasts": [forecast.to_dict() for forecast in snapshot.forecasts],
            "recommendations": [forecast.recommendation for forecast in snapshot.forecasts],
        }

    def _forecast_series(
        self,
        metric: str,
        series: list[float],
        horizon_days: int,
        recommendation_template: str,
    ) -> ForecastResult | None:
        if len(series) < 2:
            return ForecastResult(
                metric=metric,
                current_value=series[-1] if series else 0.0,
                forecast_value=series[-1] if series else 0.0,
                trend_per_day=0.0,
                confidence=0.0,
                direction="insufficient_data",
                risk_level="unknown",
                recommendation="Collect more data before forecasting",
                samples=len(series),
                details={"horizon_days": horizon_days},
            ) if series else None

        trend = self._linear_trend(series)
        forecast_value = max(0.0, series[-1] + trend * horizon_days)
        current_value = series[-1]
        confidence = self._confidence(len(series), trend)
        direction = self._direction(trend)
        risk_level = self._risk_level(metric, forecast_value, series)

        recommendation = self._recommend(metric, forecast_value, series, recommendation_template)

        return ForecastResult(
            metric=metric,
            current_value=current_value,
            forecast_value=round(forecast_value, 2),
            trend_per_day=round(trend, 4),
            confidence=round(confidence, 2),
            direction=direction,
            risk_level=risk_level,
            recommendation=recommendation,
            samples=len(series),
            details={
                "horizon_days": horizon_days,
                "min": min(series),
                "max": max(series),
                "mean": round(statistics.mean(series), 4),
            },
        )

    def _load_profitability_series(self, preferred_key: str, fallback_key: str) -> list[float]:
        path = self.reports_dir / "laura_profitability_history.jsonl"
        values: list[float] = []
        if not path.exists():
            return values

        with path.open() as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                metrics = obj.get("metrics") if isinstance(obj.get("metrics"), dict) else obj
                value = metrics.get(preferred_key)
                if value is None:
                    value = metrics.get(fallback_key)
                if value is None:
                    continue
                try:
                    values.append(float(value))
                except Exception:
                    continue

        return values

    def _load_state_series(self, preferred_key: str, fallback_key: str) -> list[float]:
        path = self.reports_dir / "laura_profitability_state.json"
        if not path.exists():
            return []

        try:
            state = json.loads(path.read_text())
        except Exception:
            return []

        values: list[float] = []
        for key in (preferred_key, fallback_key):
            if key in state and state[key] is not None:
                try:
                    values.append(float(state[key]))
                except Exception:
                    continue
        return values

    def _linear_trend(self, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(values)
        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def _confidence(self, sample_count: int, trend: float) -> float:
        base = min(0.9, sample_count / 20.0)
        trend_bonus = min(0.1, abs(trend) / 100.0)
        return min(0.95, base + trend_bonus)

    def _direction(self, trend: float) -> str:
        if trend > 0.05:
            return "increasing"
        if trend < -0.05:
            return "decreasing"
        return "stable"

    def _risk_level(self, metric: str, forecast_value: float, series: list[float]) -> str:
        if not series:
            return "unknown"
        baseline = statistics.mean(series)

        if metric in {"margin", "roas", "inventory_days"}:
            if forecast_value < baseline * 0.85:
                return "high"
            if forecast_value < baseline * 0.95:
                return "medium"
            return "low"

        if metric == "revenue":
            if forecast_value < baseline * 0.9:
                return "high"
            if forecast_value < baseline * 0.98:
                return "medium"
            return "low"

        return "low"

    def _recommend(self, metric: str, forecast_value: float, series: list[float], template: str) -> str:
        if not series:
            return "Collect more data before forecasting"

        baseline = statistics.mean(series)
        if metric == "margin":
            if forecast_value < baseline * 0.95:
                return "Protect margin with pricing and cost controls"
            return template
        if metric == "roas":
            if forecast_value < baseline * 0.9:
                return "Reduce inefficient spend and reallocate budget"
            return template
        if metric == "inventory_days":
            if forecast_value < baseline * 0.9:
                return "Replenish inventory and de-risk launch plans"
            return template
        if metric == "revenue":
            if forecast_value < baseline * 0.95:
                return "Trigger growth interventions or review pricing"
            return template
        return template

    def _derive_risks(self, forecasts: list[ForecastResult]) -> list[str]:
        risks: list[str] = []
        for forecast in forecasts:
            if forecast.risk_level in {"high", "critical"}:
                risks.append(f"{forecast.metric}:{forecast.risk_level}")

        if any(f.metric == "margin" and f.risk_level == "high" for f in forecasts) and any(
            f.metric == "roas" and f.risk_level == "high" for f in forecasts
        ):
            risks.append("margin_roas_compound_risk")

        return risks
