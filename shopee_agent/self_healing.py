"""
Phase 10: Self-Healing Infrastructure.

Aggregates health-monitoring and circuit-breaker state into a recovery-oriented
snapshot with explicit remediation actions, failover hints, and resilience
signals for production operations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .circuit_breaker import CircuitState, EndpointCircuitBreaker, get_circuit_breaker_manager
from .monitoring import HealthMonitor, get_monitor


@dataclass
class RecoveryAction:
    action: str
    target: str
    priority: str
    reason: str
    automated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelfHealingSnapshot:
    generated_at: str
    status: str
    health_status: str
    open_circuits: int
    critical_alerts: int
    degraded_alerts: int
    recovery_actions: list[RecoveryAction]
    failover_targets: list[str]
    watchpoints: list[str]
    resilience_score: float
    monitor_report: dict[str, Any]
    breaker_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["recovery_actions"] = [action.to_dict() for action in self.recovery_actions]
        return payload


class SelfHealingCoordinator:
    """Turn health signals into concrete recovery actions."""

    def __init__(
        self,
        monitor: HealthMonitor | None = None,
        breaker_manager: EndpointCircuitBreaker | None = None,
    ):
        self.monitor = monitor or get_monitor()
        self.breaker_manager = breaker_manager or get_circuit_breaker_manager()

    def evaluate(self) -> SelfHealingSnapshot:
        monitor_report = self.monitor.check_health()
        breaker_report = self.breaker_manager.get_status()

        critical_alerts = self._count_alerts(monitor_report, {"CRITICAL"})
        degraded_alerts = self._count_alerts(monitor_report, {"DEGRADED", "HIGH", "WARNING"})
        open_circuits = sum(1 for breaker in breaker_report.values() if breaker.get("state") == CircuitState.OPEN.value)

        recovery_actions = self._build_recovery_actions(monitor_report, breaker_report)
        failover_targets = self._failover_targets(breaker_report)
        watchpoints = self._watchpoints(monitor_report, breaker_report)
        resilience_score = self._resilience_score(monitor_report, breaker_report, recovery_actions)
        status = self._status(monitor_report, open_circuits, critical_alerts)

        snapshot = SelfHealingSnapshot(
            generated_at=datetime.now(UTC).isoformat(),
            status=status,
            health_status=str(monitor_report.get("overall_status", "UNKNOWN")),
            open_circuits=open_circuits,
            critical_alerts=critical_alerts,
            degraded_alerts=degraded_alerts,
            recovery_actions=recovery_actions,
            failover_targets=failover_targets,
            watchpoints=watchpoints,
            resilience_score=round(resilience_score, 2),
            monitor_report=monitor_report,
            breaker_report=breaker_report,
        )
        return snapshot

    def run_recovery_plan(self, auto_reset: bool = False) -> dict[str, Any]:
        snapshot = self.evaluate()
        reset_results: list[dict[str, Any]] = []

        if auto_reset:
            for target in snapshot.failover_targets:
                reset_results.append({"target": target, "reset": self.breaker_manager.reset_breaker(target)})

        return {
            "snapshot": snapshot.to_dict(),
            "reset_results": reset_results,
        }

    def _count_alerts(self, monitor_report: dict[str, Any], severities: set[str]) -> int:
        alerts = monitor_report.get("alerts", []) if isinstance(monitor_report, dict) else []
        return sum(1 for alert in alerts if str(alert.get("severity", "")).upper() in severities)

    def _build_recovery_actions(self, monitor_report: dict[str, Any], breaker_report: dict[str, Any]) -> list[RecoveryAction]:
        actions: list[RecoveryAction] = []
        alerts = monitor_report.get("alerts", []) if isinstance(monitor_report, dict) else []

        if any(str(alert.get("severity", "")).upper() == "CRITICAL" for alert in alerts):
            actions.append(
                RecoveryAction(
                    action="notify_incident",
                    target="operations",
                    priority="critical",
                    reason="Critical health alert detected; incident notification is required.",
                    automated=True,
                )
            )

        for name, breaker in breaker_report.items():
            if breaker.get("state") == CircuitState.OPEN.value:
                actions.append(
                    RecoveryAction(
                        action="reset_circuit_breaker",
                        target=name,
                        priority="high",
                        reason="Circuit breaker is open and needs recovery validation.",
                        automated=False,
                        metadata={"failure_count": breaker.get("failure_count", 0), "timeout_seconds": breaker.get("config", {}).get("timeout_seconds")},
                    )
                )

        if not actions:
            actions.append(
                RecoveryAction(
                    action="continue_monitoring",
                    target="system",
                    priority="low",
                    reason="No immediate recovery action required; continue passive monitoring.",
                    automated=True,
                )
            )

        return actions

    def _failover_targets(self, breaker_report: dict[str, Any]) -> list[str]:
        return [name for name, breaker in breaker_report.items() if breaker.get("state") == CircuitState.OPEN.value]

    def _watchpoints(self, monitor_report: dict[str, Any], breaker_report: dict[str, Any]) -> list[str]:
        watchpoints: list[str] = []
        if self._count_alerts(monitor_report, {"CRITICAL"}) > 0:
            watchpoints.append("critical alerts present")
        if any(breaker.get("state") == CircuitState.OPEN.value for breaker in breaker_report.values()):
            watchpoints.append("one or more circuit breakers are open")
        if self._count_alerts(monitor_report, {"DEGRADED", "HIGH", "WARNING"}) > 0:
            watchpoints.append("degraded health trends need follow-up")
        return watchpoints or ["system operating normally"]

    def _resilience_score(self, monitor_report: dict[str, Any], breaker_report: dict[str, Any], recovery_actions: list[RecoveryAction]) -> float:
        score = 100.0
        critical = self._count_alerts(monitor_report, {"CRITICAL"})
        degraded = self._count_alerts(monitor_report, {"DEGRADED", "HIGH", "WARNING"})
        open_breakers = sum(1 for breaker in breaker_report.values() if breaker.get("state") == CircuitState.OPEN.value)

        score -= critical * 35.0
        score -= degraded * 10.0
        score -= open_breakers * 15.0
        score -= max(0, len(recovery_actions) - 1) * 5.0
        return max(0.0, min(100.0, score))

    def _status(self, monitor_report: dict[str, Any], open_circuits: int, critical_alerts: int) -> str:
        status = str(monitor_report.get("overall_status", "UNKNOWN")).upper()
        if critical_alerts > 0 or open_circuits > 0 or status == "CRITICAL":
            return "needs_recovery"
        if status == "DEGRADED":
            return "monitor_and_stabilize"
        return "healthy"


def dump_self_healing_snapshot(snapshot: SelfHealingSnapshot, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
