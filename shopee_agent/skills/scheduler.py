"""Scheduled skill execution — skills with schedule= metadata run on cron."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


class PlanSchedule:
    """A scheduled plan with a cron-like time and goal state."""

    def __init__(
        self,
        plan_id: str,
        schedule: str,
        goal_state: dict[str, Any],
        current_state: dict[str, Any] | None = None,
        enabled: bool = True,
        description: str = "",
    ):
        self.plan_id = plan_id
        self.schedule = schedule  # "HH:MM"
        self.goal_state = goal_state
        self.current_state = current_state or {}
        self.enabled = enabled
        self.description = description
        self._last_run: str | None = None

    def should_run(self, current_hhmm: str, today: str) -> bool:
        return self.enabled and self.schedule == current_hhmm and self._last_run != today

    def mark_run(self) -> None:
        self._last_run = datetime.now(UTC).strftime("%Y-%m-%d")


class PlanScheduler:
    """Runs complete plans on a cron schedule (extends SkillScheduler with plan-level scheduling)."""

    def __init__(self, orchestrator: Any, check_interval: float = 30.0):
        self._orchestrator = orchestrator
        self._interval = check_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._schedules: list[PlanSchedule] = []
        self._lock = threading.Lock()

    def add_schedule(self, schedule: PlanSchedule) -> None:
        with self._lock:
            self._schedules.append(schedule)

    def remove_schedule(self, plan_id: str) -> bool:
        with self._lock:
            before = len(self._schedules)
            self._schedules = [s for s in self._schedules if s.plan_id != plan_id]
            return len(self._schedules) < before

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "plan_id": s.plan_id,
                    "schedule": s.schedule,
                    "description": s.description,
                    "enabled": s.enabled,
                    "goal_state": s.goal_state,
                    "last_run": s._last_run or "never",
                }
                for s in self._schedules
            ]

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            self._tick()
            time.sleep(self._interval)

    def _tick(self) -> None:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        current_hhmm = now.strftime("%H:%M")
        with self._lock:
            for sched in self._schedules:
                if sched.should_run(current_hhmm, today):
                    self._execute(sched)

    def _execute(self, sched: PlanSchedule) -> None:
        try:
            import asyncio
            asyncio.run(self._orchestrator.evaluate_state(
                sched.current_state, sched.goal_state,
            ))
            sched.mark_run()
        except Exception:
            pass


class SkillScheduler:
    """Runs skills on a schedule defined by their `schedule` metadata attribute.

    Schedule format: "HH:MM" in 24h UTC (e.g. "08:00", "14:30").
    """

    def __init__(self, registry: Any, runner: Callable, check_interval: float = 30.0):
        self._registry = registry
        self._runner = runner
        self._interval = check_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_runs: dict[str, str] = {}  # skill_name -> date ran

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            self._tick()
            time.sleep(self._interval)

    def _tick(self) -> None:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        current_hhmm = now.strftime("%H:%M")
        for name in self._registry.list():
            cls = self._registry.get(name)
            if cls is None:
                continue
            schedule = getattr(cls, "schedule", "")
            if not schedule or not isinstance(schedule, str):
                continue
            if self._last_runs.get(name) == today:
                continue
            if schedule == current_hhmm:
                self._execute(name)

    def _execute(self, name: str) -> None:
        try:
            import asyncio
            asyncio.run(self._runner([name]))
            self._last_runs[name] = datetime.now(UTC).strftime("%Y-%m-%d")
        except Exception:
            pass

    def status(self) -> list[dict[str, Any]]:
        """Return list of scheduled skills and their last run."""
        entries: list[dict[str, Any]] = []
        for name in self._registry.list():
            cls = self._registry.get(name)
            if cls is None:
                continue
            schedule = getattr(cls, "schedule", "")
            if schedule:
                entries.append({
                    "skill": name,
                    "schedule": schedule,
                    "last_run": self._last_runs.get(name, "never"),
                })
        return entries
