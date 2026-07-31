"""
monitoring.py - Monitoring and alerting for Laura operations
Tracks metrics and generates alerts for anomalies
"""

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .logger import error as log_error
from .logger import info, warning


@dataclass
class MetricPoint:
    """Single metric measurement"""
    timestamp: str
    value: float
    endpoint: str | None = None
    context: str | None = None


@dataclass
class MetricsWindow:
    """Rolling window of metrics"""
    name: str
    max_points: int = 1000
    points: deque = field(default_factory=lambda: deque(maxlen=1000))

    def add(self, point: MetricPoint) -> None:
        """Add a metric point"""
        self.points.append(point)

    def get_stats(self) -> dict[str, float]:
        """Get statistics for the window"""
        if not self.points:
            return {"count": 0}

        values = [p.value for p in self.points]
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "sum": sum(values),
        }

    def get_recent(self, seconds: int = 60) -> list[MetricPoint]:
        """Get points from last N seconds"""
        cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
        cutoff_iso = cutoff.isoformat()

        result = []
        for point in self.points:
            if point.timestamp >= cutoff_iso:
                result.append(point)
        return result


class HealthMonitor:
    """Monitor system health and generate alerts"""

    def __init__(self, metrics_dir: Path = Path("reports")):
        """Initialize health monitor"""
        self.metrics_dir = metrics_dir
        self.metrics_dir.mkdir(exist_ok=True)

        # Rolling windows for key metrics
        self.windows: dict[str, MetricsWindow] = {
            "api_request_latency_ms": MetricsWindow("api_request_latency_ms", max_points=1000),
            "api_errors": MetricsWindow("api_errors", max_points=500),
            "retry_attempts": MetricsWindow("retry_attempts", max_points=500),
            "rate_limit_events": MetricsWindow("rate_limit_events", max_points=500),
            "circuit_breaker_opens": MetricsWindow("circuit_breaker_opens", max_points=500),
        }

        # Thresholds for alerts
        self.thresholds = {
            "latency_p95_ms": 5000,  # Alert if p95 > 5s
            "error_rate_pct": 10.0,  # Alert if error rate > 10% (last hour)
            "retry_rate_pct": 15.0,  # Alert if retry rate > 15%
            "circuit_breaker_open_count": 2,  # Alert if 2+ breakers open
        }

        self.lock = threading.Lock()

    def record_api_latency(self, endpoint: str, latency_ms: int) -> None:
        """Record API request latency"""
        point = MetricPoint(
            timestamp=datetime.now(UTC).isoformat(),
            value=latency_ms,
            endpoint=endpoint,
            context="api_call"
        )
        with self.lock:
            self.windows["api_request_latency_ms"].add(point)

    def record_api_error(self, endpoint: str, status_code: int) -> None:
        """Record API error"""
        point = MetricPoint(
            timestamp=datetime.now(UTC).isoformat(),
            value=float(status_code),
            endpoint=endpoint,
            context="error"
        )
        with self.lock:
            self.windows["api_errors"].add(point)

    def record_retry_attempt(self, endpoint: str, attempt_number: int) -> None:
        """Record retry attempt"""
        point = MetricPoint(
            timestamp=datetime.now(UTC).isoformat(),
            value=float(attempt_number),
            endpoint=endpoint,
            context="retry"
        )
        with self.lock:
            self.windows["retry_attempts"].add(point)

    def record_rate_limit_event(self, endpoint: str) -> None:
        """Record rate limit event"""
        point = MetricPoint(
            timestamp=datetime.now(UTC).isoformat(),
            value=1.0,
            endpoint=endpoint,
            context="rate_limit"
        )
        with self.lock:
            self.windows["rate_limit_events"].add(point)

    def record_circuit_breaker_open(self, endpoint: str) -> None:
        """Record circuit breaker opening"""
        point = MetricPoint(
            timestamp=datetime.now(UTC).isoformat(),
            value=1.0,
            endpoint=endpoint,
            context="circuit_breaker"
        )
        with self.lock:
            self.windows["circuit_breaker_opens"].add(point)

    def check_health(self) -> dict[str, Any]:
        """Check overall system health and generate alerts"""
        with self.lock:
            alerts = []

            # Check latency (p95)
            latency_points = self.windows["api_request_latency_ms"].get_recent(3600)  # Last hour
            if len(latency_points) > 10:
                latencies = sorted([p.value for p in latency_points])
                p95_idx = int(len(latencies) * 0.95)
                p95 = latencies[p95_idx]
                if p95 > self.thresholds["latency_p95_ms"]:
                    alerts.append({
                        "severity": "HIGH",
                        "metric": "latency_p95_ms",
                        "value": p95,
                        "threshold": self.thresholds["latency_p95_ms"],
                        "message": f"API latency p95 is {p95:.0f}ms (threshold: {self.thresholds['latency_p95_ms']}ms)"
                    })

            # Check error rate (last hour)
            error_points = self.windows["api_errors"].get_recent(3600)
            if len(error_points) > 10:
                error_rate = (len(error_points) / (len(error_points) + len(latency_points))) * 100
                if error_rate > self.thresholds["error_rate_pct"]:
                    alerts.append({
                        "severity": "CRITICAL",
                        "metric": "error_rate_pct",
                        "value": error_rate,
                        "threshold": self.thresholds["error_rate_pct"],
                        "message": f"API error rate is {error_rate:.1f}% (threshold: {self.thresholds['error_rate_pct']}%)"
                    })

            # Check retry rate
            retry_points = self.windows["retry_attempts"].get_recent(3600)
            if len(retry_points) + len(latency_points) > 20:
                retry_rate = (len(retry_points) / (len(retry_points) + len(latency_points))) * 100
                if retry_rate > self.thresholds["retry_rate_pct"]:
                    alerts.append({
                        "severity": "HIGH",
                        "metric": "retry_rate_pct",
                        "value": retry_rate,
                        "threshold": self.thresholds["retry_rate_pct"],
                        "message": f"Retry rate is {retry_rate:.1f}% (threshold: {self.thresholds['retry_rate_pct']}%)"
                    })

            # Check circuit breaker opens (last hour)
            cb_opens = self.windows["circuit_breaker_opens"].get_recent(3600)
            if len(cb_opens) > self.thresholds["circuit_breaker_open_count"]:
                alerts.append({
                    "severity": "CRITICAL",
                    "metric": "circuit_breaker_opens",
                    "value": len(cb_opens),
                    "threshold": self.thresholds["circuit_breaker_open_count"],
                    "message": f"{len(cb_opens)} circuit breakers opened in last hour"
                })

            # Generate health report
            critical_alerts = sum(1 for alert in alerts if alert["severity"] == "CRITICAL")
            high_alerts = sum(1 for alert in alerts if alert["severity"] == "HIGH")
            warning_alerts = sum(1 for alert in alerts if alert["severity"] == "WARNING")
            health_score = 100

            # Score is intentionally deterministic and easy to interpret:
            # critical alerts hurt most, followed by high and warning alerts.
            health_score -= critical_alerts * 35
            health_score -= high_alerts * 15
            health_score -= warning_alerts * 5

            latency_points = self.windows["api_request_latency_ms"].get_recent(3600)
            if len(latency_points) > 10:
                latencies = sorted([p.value for p in latency_points])
                p95_idx = int(len(latencies) * 0.95)
                p95 = latencies[p95_idx]
                if p95 > self.thresholds["latency_p95_ms"]:
                    health_score -= min(20, int((p95 - self.thresholds["latency_p95_ms"]) / 250))

            health_score = max(0, min(100, health_score))

            report = {
                "timestamp": datetime.now(UTC).isoformat(),
                "health_score": health_score,
                "overall_status": "CRITICAL" if any(a["severity"] == "CRITICAL" for a in alerts) else
                                 "DEGRADED" if alerts else "HEALTHY",
                "alerts": alerts,
                "metrics": {
                    name: window.get_stats()
                    for name, window in self.windows.items()
                },
            }

            return report

    def save_health_report(self) -> Path:
        """Save health report to file"""
        report = self.check_health()

        # Save as JSON
        report_file = self.metrics_dir / "laura_health_latest.json"
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))

        # Log alerts
        for alert in report["alerts"]:
            if alert["severity"] == "CRITICAL":
                log_error("Health alert: %s" % alert['message'], **alert)
            else:
                warning("Health alert: %s" % alert['message'], **alert)

        return report_file


# Default global monitor instance
_default_monitor: HealthMonitor | None = None


def get_monitor() -> HealthMonitor:
    """Get or create default monitor"""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = HealthMonitor()
    return _default_monitor


def initialize_monitoring() -> None:
    """Initialize monitoring system"""
    get_monitor()
    info("Monitoring system initialized")


# Convenience functions
def record_api_latency(endpoint: str, latency_ms: int) -> None:
    """Record API latency"""
    get_monitor().record_api_latency(endpoint, latency_ms)


def record_api_error(endpoint: str, status_code: int) -> None:
    """Record API error"""
    get_monitor().record_api_error(endpoint, status_code)


def record_retry_attempt(endpoint: str, attempt_number: int) -> None:
    """Record retry attempt"""
    get_monitor().record_retry_attempt(endpoint, attempt_number)


def record_rate_limit_event(endpoint: str) -> None:
    """Record rate limit event"""
    get_monitor().record_rate_limit_event(endpoint)


def record_circuit_breaker_open(endpoint: str) -> None:
    """Record circuit breaker open"""
    get_monitor().record_circuit_breaker_open(endpoint)


def check_health() -> dict[str, Any]:
    """Check system health"""
    return get_monitor().check_health()


def save_health_report() -> Path:
    """Save health report"""
    return get_monitor().save_health_report()
