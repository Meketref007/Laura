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

        # escolhe o metodo com melhor holdout (RMSE) entre linear e Holt+sazonal
        method = "linear_trend"
        trend = self._linear_trend(series)
        forecast_value = max(0.0, series[-1] + trend * horizon_days)

        if len(series) >= 6:
            holt = self._holt_linear(series, horizon_days)
            seasonal, season_factors = self._seasonal_adjust(series, horizon_days)
            rmse_linear = self._holdout_rmse(series, method="linear_trend")
            rmse_holt = self._holdout_rmse(series, method="holt")
            rmse_seasonal = self._holdout_rmse(series, method="seasonal") if season_factors else float("inf")

            best = min(
                (rmse_linear, "linear_trend"),
                (rmse_holt, "holt_linear"),
                (rmse_seasonal, "holt_seasonal"),
                key=lambda pair: pair[0],
            )
            method = best[1]
            if method == "holt_linear":
                forecast_value = max(0.0, holt)
            elif method == "holt_seasonal":
                forecast_value = max(0.0, seasonal)
                trend = self._holt_trend(series)

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
                "method": method,
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

    def _holt_linear(self, values: list[float], horizon_days: int, alpha: float = 0.4, beta: float = 0.2) -> float:
        """Suavizacao exponencial dupla (Holt): nivel + tendencia, extrapola o horizonte."""
        if len(values) < 2:
            return values[-1] if values else 0.0
        level = values[0]
        trend = values[1] - values[0] if len(values) > 1 else 0.0
        for i in range(1, len(values)):
            last_level = level
            level = alpha * values[i] + (1 - alpha) * (level + trend)
            trend = beta * (level - last_level) + (1 - beta) * trend
        return level + trend * horizon_days

    def _holt_trend(self, values: list[float], alpha: float = 0.4, beta: float = 0.2) -> float:
        """Tendencia suavizada de Holt (para reportar trend_per_day)."""
        if len(values) < 2:
            return 0.0
        level = values[0]
        trend = values[1] - values[0]
        for i in range(1, len(values)):
            last_level = level
            level = alpha * values[i] + (1 - alpha) * (level + trend)
            trend = beta * (level - last_level) + (1 - beta) * trend
        return trend

    @staticmethod
    def _seasonal_period(values: list[float]) -> int:
        """Detecta o periodo sazonal mais provavel (7 = semanal, 30 = mensal, 0 = sem padrao)."""
        n = len(values)
        if n < 14:
            return 0
        for period in (7, 30):
            if n < period * 2:
                continue
            mean_full = statistics.mean(values)
            sse_within = 0.0
            sse_overall = sum((v - mean_full) ** 2 for v in values)
            for offset in range(period):
                bucket = values[offset::period]
                if not bucket:
                    continue
                bucket_mean = statistics.mean(bucket)
                sse_within += sum((v - bucket_mean) ** 2 for v in bucket)
            if sse_overall > 0 and sse_within / sse_overall < 0.85:
                return period
        return 0

    def _seasonal_adjust(self, values: list[float], horizon_days: int) -> tuple[float, dict[int, float]]:
        """Previsao Holt + fator sazonal (proximo periodo). Retorna (previsao, fatores)."""
        period = self._seasonal_period(values)
        factors: dict[int, float] = {}
        if period == 0 or len(values) < period * 2:
            return self._holt_linear(values, horizon_days), factors

        global_mean = statistics.mean(values)
        for offset in range(period):
            bucket = values[offset::period]
            if bucket:
                factors[offset] = statistics.mean(bucket) / max(1e-9, global_mean)

        last_index = len(values) - 1
        next_offsets = [(last_index + i + 1) % period for i in range(horizon_days)]
        seasonal_target = sum(factors.get(offset, 1.0) for offset in next_offsets)
        return self._holt_linear(values, horizon_days) * seasonal_target / max(1e-9, horizon_days), factors

    @staticmethod
    def _holdout_rmse(values: list[float], method: str, holdout: int = 5) -> float:
        """Treina nos primeiros len-holdout pontos e mede o RMSE nos ultimos `holdout`."""
        if len(values) < holdout + 3:
            return float("inf")
        train = values[:-holdout]
        actual = values[-holdout:]
        errors = 0.0
        for step, y_true in enumerate(actual, start=1):
            if method == "linear_trend":
                trend = PredictiveAnalytics._linear_trend_static(train)
                y_pred = max(0.0, train[-1] + trend * step)
            elif method == "holt":
                y_pred = max(0.0, PredictiveAnalytics._holt_static(train, step))
            elif method == "seasonal":
                y_pred, _ = PredictiveAnalytics._seasonal_static(train, step)
            else:
                y_pred = train[-1]
            errors += (y_true - y_pred) ** 2
        return (errors / holdout) ** 0.5

    @staticmethod
    def _linear_trend_static(values: list[float]) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(values)
        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _holt_static(values: list[float], horizon: int) -> float:
        if len(values) < 2:
            return values[-1] if values else 0.0
        level = values[0]
        trend = values[1] - values[0]
        for i in range(1, len(values)):
            last_level = level
            level = 0.4 * values[i] + 0.6 * (level + trend)
            trend = 0.2 * (level - last_level) + 0.8 * trend
        return level + trend * horizon

    @staticmethod
    def _seasonal_static(values: list[float], horizon: int) -> tuple[float, dict[int, float]]:
        period = PredictiveAnalytics._seasonal_period(values)
        factors: dict[int, float] = {}
        if period == 0 or len(values) < period * 2:
            return PredictiveAnalytics._holt_static(values, horizon), factors
        global_mean = statistics.mean(values)
        for offset in range(period):
            bucket = values[offset::period]
            if bucket:
                factors[offset] = statistics.mean(bucket) / max(1e-9, global_mean)
        last_index = len(values) - 1
        next_offsets = [(last_index + i + 1) % period for i in range(horizon)]
        seasonal_target = sum(factors.get(offset, 1.0) for offset in next_offsets)
        return (
            PredictiveAnalytics._holt_static(values, horizon) * seasonal_target / max(1e-9, horizon),
            factors,
        )

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
