"""
PHASE 17: Advanced Analytics & Trending
Provides historical data analysis, trend detection, and anomaly detection
"""

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class AdvancedAnalytics:
    """Advanced analytics with trend detection and anomaly alerting"""

    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)

    def get_historical_metrics(self, days: int = 30) -> dict[str, Any]:
        """Get metrics for specified period (30/90/365 day views)"""
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        metrics = {
            "period_days": days,
            "period_start": cutoff_date,
            "period_end": datetime.now().isoformat(),
            "alerts": self._get_alerts_in_period(cutoff_date),
            "refunds": self._get_refunds_in_period(cutoff_date),
            "trends": self._analyze_trends(days),
            "anomalies": self._detect_anomalies(days),
        }
        return metrics

    def analyze_trends(self, metric_name: str, days: int = 30) -> dict[str, Any]:
        """Analyze trends for specific metric"""
        data = self._collect_metric_history(metric_name, days)

        if not data or len(data) < 2:
            return {
                "metric": metric_name,
                "status": "insufficient_data",
                "data_points": len(data)
            }

        values = [d.get('value', 0) for d in data]
        trend = self._calculate_trend(values)

        return {
            "metric": metric_name,
            "period_days": days,
            "data_points": len(values),
            "trend": trend,
            "mean": statistics.mean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0,
            "min": min(values),
            "max": max(values),
            "direction": "📈 INCREASING" if trend > 0.05 else "📉 DECREASING" if trend < -0.05 else "➡️ STABLE",
            "prediction_next_period": self._forecast_next_period(values),
        }

    def detect_anomalies(self, threshold_stddev: float = 2.0) -> list[dict[str, Any]]:
        """Detect anomalies using statistical methods"""
        anomalies = []

        # Check alerts for spikes
        alerts = self._read_jsonl("laura_alerts_history.jsonl")
        if alerts:
            alert_counts = self._aggregate_by_hour(alerts)
            mean = statistics.mean(alert_counts)
            stdev = statistics.stdev(alert_counts) if len(alert_counts) > 1 else 0

            for timestamp, count in alert_counts.items():
                if stdev > 0 and abs(count - mean) > threshold_stddev * stdev:
                    anomalies.append({
                        "type": "alert_spike",
                        "timestamp": timestamp,
                        "value": count,
                        "threshold": mean + threshold_stddev * stdev,
                        "severity": "HIGH" if count > mean + 2*threshold_stddev*stdev else "MEDIUM"
                    })

        # Check refunds for spikes
        refunds = self._read_jsonl("laura_refunds_history.jsonl")
        if refunds:
            refund_counts = self._aggregate_by_hour(refunds)
            mean = statistics.mean(refund_counts)
            stdev = statistics.stdev(refund_counts) if len(refund_counts) > 1 else 0

            for timestamp, count in refund_counts.items():
                if stdev > 0 and abs(count - mean) > threshold_stddev * stdev:
                    anomalies.append({
                        "type": "refund_spike",
                        "timestamp": timestamp,
                        "value": count,
                        "threshold": mean + threshold_stddev * stdev,
                        "severity": "HIGH" if count > mean + 2*threshold_stddev*stdev else "MEDIUM"
                    })

        return sorted(anomalies, key=lambda x: x['timestamp'], reverse=True)[:10]

    def predict_refund_rate(self, days_ahead: int = 7) -> dict[str, Any]:
        """Predict refund rate for next N days"""
        refunds = self._read_jsonl("laura_refunds_history.jsonl")
        if not refunds:
            return {"status": "no_data"}

        daily_refunds = self._aggregate_by_day(refunds)
        if len(daily_refunds) < 7:
            return {"status": "insufficient_history", "days_available": len(daily_refunds)}

        values = list(daily_refunds.values())
        forecast = self._forecast_next_period(values, days_ahead)

        return {
            "historical_avg": statistics.mean(values),
            "forecast_days": days_ahead,
            "predicted_value": forecast,
            "confidence": 0.75 if len(values) >= 30 else 0.50 if len(values) >= 14 else 0.25,
            "recommendation": self._generate_recommendation(forecast, statistics.mean(values))
        }

    def get_trending_report(self) -> dict[str, Any]:
        """Generate comprehensive trending report"""
        return {
            "timestamp": datetime.now().isoformat(),
            "periods": {
                "7_day": self.get_historical_metrics(7),
                "30_day": self.get_historical_metrics(30),
                "90_day": self.get_historical_metrics(90),
            },
            "trends": {
                "alerts": self.analyze_trends("alerts", 30),
                "refunds": self.analyze_trends("refunds", 30),
            },
            "anomalies": self.detect_anomalies(),
            "predictions": {
                "refund_rate_7d": self.predict_refund_rate(7),
            }
        }

    # Helper methods

    def _get_alerts_in_period(self, cutoff_date: str) -> int:
        """Count alerts since cutoff date"""
        alerts = self._read_jsonl("laura_alerts_history.jsonl")
        return sum(1 for a in alerts if a.get('timestamp', '') >= cutoff_date)

    def _get_refunds_in_period(self, cutoff_date: str) -> int:
        """Count refunds since cutoff date"""
        refunds = self._read_jsonl("laura_refunds_history.jsonl")
        return sum(1 for r in refunds if r.get('timestamp', '') >= cutoff_date)

    def _analyze_trends(self, days: int) -> dict[str, Any]:
        """Analyze major trends"""
        return {
            "alerts_trend": self.analyze_trends("alerts", days),
            "refunds_trend": self.analyze_trends("refunds", days),
        }

    def _detect_anomalies(self, days: int) -> list[dict[str, Any]]:
        """Detect anomalies in period"""
        return self.detect_anomalies()

    def _collect_metric_history(self, metric_name: str, days: int) -> list[dict[str, Any]]:
        """Collect historical metric data"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        if metric_name == "alerts":
            alerts = self._read_jsonl("laura_alerts_history.jsonl")
            return [a for a in alerts if a.get('timestamp', '') >= cutoff]
        elif metric_name == "refunds":
            refunds = self._read_jsonl("laura_refunds_history.jsonl")
            return [r for r in refunds if r.get('timestamp', '') >= cutoff]
        return []

    def _calculate_trend(self, values: list[float]) -> float:
        """Calculate trend coefficient (-1 to 1)"""
        if len(values) < 2:
            return 0

        # Simple linear regression coefficient
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(values)

        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0
        return numerator / denominator

    def _forecast_next_period(self, values: list[float], periods: int = 1) -> float:
        """Simple forecast for next period"""
        if not values:
            return 0

        # Use exponential smoothing
        alpha = 0.3
        last = values[-1]
        for val in values[-3:]:
            last = alpha * val + (1 - alpha) * last

        return round(last, 2)

    def _aggregate_by_hour(self, items: list[dict]) -> dict[str, int]:
        """Aggregate items by hour"""
        hourly = {}
        for item in items:
            ts = item.get('timestamp', '')[:13]  # Hour precision
            hourly[ts] = hourly.get(ts, 0) + 1
        return hourly

    def _aggregate_by_day(self, items: list[dict]) -> dict[str, int]:
        """Aggregate items by day"""
        daily = {}
        for item in items:
            ts = item.get('timestamp', '')[:10]  # Day precision
            daily[ts] = daily.get(ts, 0) + 1
        return daily

    def _read_jsonl(self, filename: str) -> list[dict]:
        """Read JSONL file"""
        filepath = self.reports_dir / filename
        if not filepath.exists():
            return []

        try:
            lines = filepath.read_text().strip().split('\n')
            return [json.loads(line) for line in lines if line]
        except Exception:
            return []

    def _generate_recommendation(self, predicted: float, historical_avg: float) -> str:
        """Generate recommendation based on prediction"""
        if predicted > historical_avg * 1.2:
            return "⚠️ Refund rate likely to increase - review product quality"
        elif predicted < historical_avg * 0.8:
            return "✅ Refund rate likely to decrease - good trend"
        else:
            return "➡️ Refund rate expected to remain stable"

