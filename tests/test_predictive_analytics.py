"""Tests for Phase 39 predictive analytics."""

from __future__ import annotations

import json
import statistics

from shopee_agent.decision_engine import EconomicContext
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.predictive_analytics import PredictiveAnalytics


class DummyEngine:
    def process_signal(self, signal, context):
        return []


def write_profit_history(path, values):
    with path.open("w", encoding="utf-8") as fh:
        for idx, value in enumerate(values):
            fh.write(
                json.dumps(
                    {
                        "timestamp": f"2026-05-0{idx + 1}T12:00:00+00:00",
                        "metrics": {
                            "daily_revenue_usd": value[0],
                            "gross_margin_pct": value[1],
                            "actual_roas": value[2],
                        },
                    }
                )
                + "\n"
            )


class TestPredictiveAnalytics:
    def test_forecast_overview_returns_multiple_metrics(self, tmp_path):
        history = tmp_path / "laura_profitability_history.jsonl"
        write_profit_history(
            history,
            [
                (4000, 15.0, 1.8),
                (4200, 15.5, 1.9),
                (4400, 16.0, 2.0),
                (4600, 16.5, 2.1),
                (4800, 17.0, 2.2),
            ],
        )

        analytics = PredictiveAnalytics(reports_dir=str(tmp_path))
        snapshot = analytics.forecast_overview(horizon_days=7)

        assert snapshot.horizon_days == 7
        assert len(snapshot.forecasts) >= 3
        metrics = {forecast.metric for forecast in snapshot.forecasts}
        assert {"revenue", "margin", "roas"}.issubset(metrics)
        assert any(forecast.direction == "increasing" for forecast in snapshot.forecasts)

    def test_forecast_detects_risk(self, tmp_path):
        history = tmp_path / "laura_profitability_history.jsonl"
        write_profit_history(
            history,
            [
                (5200, 18.0, 2.4),
                (5000, 17.2, 2.3),
                (4700, 16.0, 2.1),
                (4400, 14.8, 1.9),
                (4100, 13.5, 1.7),
            ],
        )

        analytics = PredictiveAnalytics(reports_dir=str(tmp_path))
        summary = analytics.predict_risk_summary(horizon_days=7)

        assert summary["high_risk_metrics"]
        assert summary["recommendations"]

    def test_seasonal_detection_weekly(self):
        """Serie com fim de semana forte deve detectar periodo 7 (semanal)."""
        values: list[float] = []
        for _week in range(6):
            for dow in range(7):
                values.append(50.0 if dow in (5, 6) else 30.0)
        assert PredictiveAnalytics._seasonal_period(values) == 7

    def test_seasonal_factors_reflect_pattern(self):
        values: list[float] = []
        for _week in range(6):
            for dow in range(7):
                values.append(50.0 if dow in (5, 6) else 30.0)
        _forecast, factors = PredictiveAnalytics._seasonal_static(values, horizon=1)
        weekend_avg = (factors[5] + factors[6]) / 2
        weekday_avg = statistics.mean([factors[i] for i in range(5)])
        assert weekend_avg > weekday_avg

    def test_holt_outperforms_linear_on_uptrend_holdout(self):
        """Com tendencia clara, o holdout do Holt deve ser melhor que o linear."""
        values = [float(10 + i * 1.5 + (i % 3)) for i in range(30)]
        rmse_holt = PredictiveAnalytics._holdout_rmse(values, "holt")
        rmse_linear = PredictiveAnalytics._holdout_rmse(values, "linear_trend")
        assert rmse_holt <= rmse_linear

    def test_forecast_reports_method(self, tmp_path):
        """O ForecastResult deve reportar qual metodo foi usado."""
        history = tmp_path / "laura_profitability_history.jsonl"
        values = [float(10 + i * 1.5) for i in range(30)]
        write_profit_history(history, [(v, 16.0, 2.0) for v in values])

        analytics = PredictiveAnalytics(reports_dir=str(tmp_path))
        result = analytics.forecast_revenue(horizon_days=7)

        assert result is not None
        assert result.details.get("method") in {"linear_trend", "holt_linear", "holt_seasonal"}
        assert result.forecast_value > 0


class TestPredictiveIntegration:
    def test_decision_integrator_includes_predictive_snapshot(self, tmp_path, monkeypatch):
        history = tmp_path / "laura_profitability_history.jsonl"
        write_profit_history(
            history,
            [
                (4200, 15.0, 1.9),
                (4300, 15.3, 2.0),
                (4400, 15.7, 2.05),
                (4500, 16.0, 2.1),
            ],
        )

        engine = DummyEngine()
        analytics = PredictiveAnalytics(reports_dir=str(tmp_path))
        integrator = DecisionIntegrator(
            engine=engine,
            store_id="test_store",
            metrics_dir=str(tmp_path),
            predictive_analytics=analytics,
        )

        monkeypatch.setattr(integrator, "collect_signals_from_metrics", lambda: [])
        monkeypatch.setattr(
            integrator,
            "build_economic_context",
            lambda: EconomicContext(
                current_margin_pct=16.0,
                margin_target_pct=18.0,
                daily_revenue_usd=4500.0,
                cash_buffer_usd=50000.0,
                inventory_days_on_hand=10,
                stock_risk_level="normal",
                active_promotions=0,
                advertising_spend_daily_usd=500.0,
                advertising_roas=2.1,
                customer_satisfaction_score=80.0,
                recent_anomalies=[],
            ),
        )

        result = integrator.process_cycle()

        assert result["predictive_analytics"] is not None
        assert result["predictive_analytics"]["forecasts"]
        assert integrator.last_predictive_snapshot is not None
