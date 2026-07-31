"""Planner alerts — rule-based notifications based on planner behavior.

Integrates with TelegramBot and webhook for push notifications.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PlannerAlert:
    """A single alert rule that watches planner behavior."""

    def __init__(
        self,
        name: str,
        description: str,
        check_fn: Callable[[dict[str, Any]], bool],
        message_fn: Callable[[dict[str, Any]], str],
        cooldown_seconds: float = 300.0,
    ):
        self.name = name
        self.description = description
        self.check_fn = check_fn
        self.message_fn = message_fn
        self.cooldown_seconds = cooldown_seconds
        self._last_fired: float = 0.0


class PlannerAlertManager:
    """Manages alert rules and tracks which have fired."""

    def __init__(self, path: str = "reports/planner_alerts.jsonl"):
        self._alerts: list[PlannerAlert] = []
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._notify_fn: Callable[[str], None] | None = None

    def set_notify(self, fn: Callable[[str], None] | None) -> None:
        """Set a notification function (e.g. TelegramBot.send_text)."""
        self._notify_fn = fn

    def add_alert(self, alert: PlannerAlert) -> None:
        self._alerts.append(alert)

    def check_all(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Run all alert checks against the given planner context.

        Returns list of fired alerts (with dedup by cooldown).
        """
        import time

        fired: list[dict[str, Any]] = []
        now = time.time()
        with self._lock:
            for alert in self._alerts:
                if alert.check_fn(context):
                    if now - alert._last_fired >= alert.cooldown_seconds:
                        alert._last_fired = now
                        entry = {
                            "alert": alert.name,
                            "description": alert.description,
                            "message": alert.message_fn(context),
                            "timestamp": datetime.now(UTC).isoformat(),
                            "context": {k: v for k, v in context.items() if isinstance(v, (str, int, float, bool, list))},
                        }
                        fired.append(entry)
                        self._append_log(entry)
                        if self._notify_fn:
                            try:
                                msg = f"[PlannerAlert] {entry['alert']}: {entry['message']}"
                                self._notify_fn(msg)
                            except Exception:
                                pass
        return fired

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().split("\n")
        results = []
        for line in lines[-limit:]:
            if line.strip():
                try:
                    results.append(json.loads(line))
                except Exception:
                    pass
        return results

    def _append_log(self, entry: dict[str, Any]) -> None:
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


def default_planner_alerts() -> PlannerAlertManager:
    """Create a manager with built-in alert rules."""
    manager = PlannerAlertManager()

    manager.add_alert(PlannerAlert(
        name="no_plan_found",
        description="GOAP planner failed to find a plan",
        check_fn=lambda ctx: ctx.get("plan_status") == "no_plan",
        message_fn=lambda ctx: f"GOAP did not find a plan from {ctx.get('num_actions', 0)} available actions",
    ))

    manager.add_alert(PlannerAlert(
        name="consecutive_failures",
        description="Multiple consecutive plan execution failures",
        check_fn=lambda ctx: ctx.get("consecutive_failures", 0) >= 3,
        message_fn=lambda ctx: f"Plan failed {ctx.get('consecutive_failures', 0)} times in a row",
    ))

    manager.add_alert(PlannerAlert(
        name="high_cost_plan",
        description="Plan cost exceeded threshold",
        check_fn=lambda ctx: ctx.get("total_cost", 0) > (ctx.get("cost_threshold", 10.0)),
        message_fn=lambda ctx: f"Plan cost {ctx.get('total_cost', 0):.1f} exceeds threshold {ctx.get('cost_threshold', 10.0):.1f}",
    ))

    manager.add_alert(PlannerAlert(
        name="budget_exceeded",
        description="Planner budget was exceeded and plan was pruned",
        check_fn=lambda ctx: ctx.get("budget_exceeded", False),
        message_fn=lambda ctx: f"Budget {ctx.get('max_budget', 0)} was exceeded, plan may be incomplete",
    ))

    manager.add_alert(PlannerAlert(
        name="learning_drift",
        description="A skill cost has drifted significantly from its base",
        check_fn=lambda ctx: bool(ctx.get("cost_drifts", [])),
        message_fn=lambda ctx: f"Skills with cost drift: {', '.join(ctx.get('cost_drifts', []))}",
    ))

    return manager
