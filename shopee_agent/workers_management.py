"""
CLI-friendly management of all background workers.
Provides WorkersManager for inspecting, pausing, resuming, and collecting
stats from EventBus workers and worker files in reports/.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .event_bus import AsyncEventBus, DeadLetterEvent
from .workers import (
    AutoSkillWorker,
    BaseWorker,
    DecisionWorker,
    MetricWorker,
    NotificationWorker,
    OrchestrationWorker,
    OutcomeWorker,
    PlanningWorker,
    RefundWorker,
)

# ---------------------------------------------------------------------------
# Known worker classes (discovered from workers.py)
# ---------------------------------------------------------------------------
_BUILTIN_WORKER_CLASSES: dict[str, type] = {
    "decision": DecisionWorker,
    "outcome": OutcomeWorker,
    "notification": NotificationWorker,
    "metric": MetricWorker,
    "orchestration": OrchestrationWorker,
    "planning": PlanningWorker,
    "refund": RefundWorker,
    "auto_skill": AutoSkillWorker,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _worker_label(name: str) -> str:
    """Return a human-friendly label for a worker name."""
    labels = {
        "decision": "Decision Engine",
        "outcome": "Outcome Tracker",
        "notification": "Notification Dispatcher",
        "metric": "Metrics Aggregator",
        "orchestration": "Orchestrator",
        "planning": "Strategic Planner",
        "refund": "Refund Processor",
        "auto_skill": "Auto Skill Runner",
    }
    return labels.get(name, name.replace("_", " ").title())


class WorkersManager:
    """Manages discovery, inspection, pause/resume, and stats of background workers."""

    def __init__(self, event_bus: AsyncEventBus | None = None, reports_dir: str = "reports"):
        self._bus = event_bus
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._reports_dir / "workers_state.json"

        # In-memory state: worker_name -> dict
        self._state: dict[str, dict[str, Any]] = {}
        # Worker instances discovered at runtime (keyed by name)
        self._instances: dict[str, BaseWorker] = {}
        # Paused set
        self._paused: set[str] = set()
        # Error counters (name -> count)
        self._error_counts: dict[str, int] = defaultdict(int)
        # Processed counters (name -> count)
        self._processed_counts: dict[str, int] = defaultdict(int)
        # Latency tracking for stats
        self._latency_buckets: dict[str, list[float]] = defaultdict(list)

        self._load_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._state = data.get("state", {})
                self._paused = set(data.get("paused", []))
                self._error_counts = defaultdict(int, data.get("error_counts", {}))
                self._processed_counts = defaultdict(int, data.get("processed_counts", {}))
        except Exception:
            pass

    def _save_state(self) -> None:
        data = {
            "state": self._state,
            "paused": sorted(self._paused),
            "error_counts": dict(self._error_counts),
            "processed_counts": dict(self._processed_counts),
            "saved_at": _now_iso(),
        }
        try:
            self._state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_from_bus(self) -> dict[str, dict[str, Any]]:
        """Discover worker names and metadata from event bus handler registrations."""
        discovered: dict[str, dict[str, Any]] = {}
        if self._bus is None:
            return discovered

        bus_stats = self._bus.stats()
        bus_dlq = self._bus.dlq()
        is_running = getattr(self._bus, "_running", False)

        # Walk registered handler names
        handler_names: dict[str, list[str]] = getattr(self._bus, "_handler_names", {})
        seen_workers: set[str] = set()
        for event_type, names in handler_names.items():
            for name in names:
                if name and name != "?":
                    seen_workers.add(name)

        for wname in sorted(seen_workers):
            discovered[wname] = {
                "name": wname,
                "label": _worker_label(wname),
                "source": "event_bus",
                "running": is_running,
                "paused": wname in self._paused,
                "events_processed": self._processed_counts.get(wname, 0),
                "error_count": self._error_counts.get(wname, 0),
            }

        if is_running:
            discovered["_bus"] = {
                "name": "_bus",
                "label": "Event Bus Core",
                "source": "event_bus",
                "running": True,
                "paused": False,
                "queue_queued": bus_stats.queued,
                "queue_processed": bus_stats.processed,
                "queue_failed": bus_stats.failed,
                "queue_retried": bus_stats.retried,
                "dlq_count": bus_stats.dlq_count,
                "dlq_events": [_dlq_to_dict(e) for e in bus_dlq[:20]],
            }
        return discovered

    def _discover_from_reports(self) -> dict[str, dict[str, Any]]:
        """Discover worker-like activity from reports directory files."""
        discovered: dict[str, dict[str, Any]] = {}

        # Worker output files in reports/ indicate activity
        report_indicators: list[tuple[str, str, str]] = [
            ("decision", "effectiveness_metrics.jsonl", "worker_output"),
            ("orchestration", "orchestration_plans.jsonl", "worker_output"),
            ("planning", "strategic_plans.jsonl", "worker_output"),
            ("outcome", "effectiveness_metrics.jsonl", "worker_output"),
        ]

        for wname, filename, source in report_indicators:
            fpath = self._reports_dir / filename
            line_count = 0
            last_modified = None
            if fpath.exists():
                try:
                    line_count = sum(1 for _ in fpath.open("r", encoding="utf-8"))
                    mtime = os.path.getmtime(str(fpath))
                    last_modified = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
                except Exception:
                    pass
                discovered[wname] = {
                    "name": wname,
                    "label": _worker_label(wname),
                    "source": source,
                    "report_file": filename,
                    "report_lines": line_count,
                    "last_modified": last_modified,
                }

        # Also check for any worker jsonl files not yet covered
        for fpath in self._reports_dir.glob("*worker*.jsonl"):
            wname = fpath.stem.replace("_", "-").replace("-", "_")
            if wname not in discovered:
                try:
                    line_count = sum(1 for _ in fpath.open("r", encoding="utf-8"))
                    mtime = os.path.getmtime(str(fpath))
                    last_modified = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
                except Exception:
                    line_count = 0
                    last_modified = None
                discovered[wname] = {
                    "name": wname,
                    "label": _worker_label(wname),
                    "source": "report_file",
                    "report_file": fpath.name,
                    "report_lines": line_count,
                    "last_modified": last_modified,
                }

        return discovered

    def _discover_from_classes(self) -> dict[str, dict[str, Any]]:
        """Discover workers from the built-in class registry."""
        discovered: dict[str, dict[str, Any]] = {}
        for wname, cls in _BUILTIN_WORKER_CLASSES.items():
            discovered[wname] = {
                "name": wname,
                "label": _worker_label(wname),
                "source": "builtin",
                "class_name": cls.__name__,
                "running": wname in self._instances,
                "paused": wname in self._paused,
                "events_processed": self._processed_counts.get(wname, 0),
                "error_count": self._error_counts.get(wname, 0),
            }
        return discovered

    # ------------------------------------------------------------------
    # Instance tracking
    # ------------------------------------------------------------------

    def register_instance(self, worker: BaseWorker) -> None:
        """Register a live worker instance for management."""
        self._instances[worker.name] = worker
        if worker.name not in self._state:
            self._state[worker.name] = {"registered_at": _now_iso()}
        self._save_state()

    def unregister_instance(self, worker_name: str) -> None:
        """Remove a previously registered instance."""
        self._instances.pop(worker_name, None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_workers(self) -> list[dict[str, Any]]:
        """Return all registered workers with their current status."""
        merged: dict[str, dict[str, Any]] = {}

        for src in (self._discover_from_bus, self._discover_from_classes, self._discover_from_reports):
            for name, info in src().items():
                if name == "_bus":
                    continue
                if name not in merged:
                    merged[name] = {}
                merged[name].update(info)

        # Enrich with live instance data and persisted state
        for name, info in merged.items():
            instance = self._instances.get(name)
            if instance is not None:
                info["running"] = True
                info["paused"] = name in self._paused
                info["events_processed"] = instance._events_processed
                info["error_count"] = self._error_counts.get(name, 0)
                # Estimate queue size from bus stats (per-handler not available, so show bus-level)
                if self._bus is not None:
                    bus_stats = self._bus.stats()
                    info["queue_size"] = bus_stats.queued
            else:
                info.setdefault("running", False)
                info.setdefault("paused", name in self._paused)
                info.setdefault("events_processed", self._processed_counts.get(name, 0))
                info.setdefault("error_count", self._error_counts.get(name, 0))

            info.setdefault("label", _worker_label(name))
            info.setdefault("last_active", self._state.get(name, {}).get("last_active"))
            info.setdefault("registered_at", self._state.get(name, {}).get("registered_at"))

        return sorted(merged.values(), key=lambda w: w.get("name", ""))

    def get_worker_status(self, worker_name: str) -> dict[str, Any]:
        """Detailed status of a specific worker."""
        for entry in self.list_workers():
            if entry.get("name") == worker_name:
                instance = self._instances.get(worker_name)
                if instance is not None and self._bus is not None:
                    bus_stats = self._bus.stats()
                    entry["bus_stats"] = {
                        "queued": bus_stats.queued,
                        "processed": bus_stats.processed,
                        "failed": bus_stats.failed,
                        "retried": bus_stats.retried,
                        "dlq_count": bus_stats.dlq_count,
                    }
                    entry["dlq"] = [_dlq_to_dict(e) for e in self._bus.dlq()[:10]]
                entry["paused"] = worker_name in self._paused
                entry["state"] = self._state.get(worker_name, {})
                return entry
        return {"error": f"Worker '{worker_name}' not found", "name": worker_name}

    def pause_worker(self, worker_name: str) -> bool:
        """Pause a worker (prevents processing new events)."""
        if worker_name not in _BUILTIN_WORKER_CLASSES and worker_name not in self._instances:
            # Also check if it showed up in discovery
            all_workers = {w["name"] for w in self.list_workers()}
            if worker_name not in all_workers:
                return False
        self._paused.add(worker_name)
        self._state.setdefault(worker_name, {})["paused_at"] = _now_iso()
        self._save_state()
        return True

    def resume_worker(self, worker_name: str) -> bool:
        """Resume a previously paused worker."""
        if worker_name not in self._paused:
            return False
        self._paused.discard(worker_name)
        self._state.setdefault(worker_name, {})["resumed_at"] = _now_iso()
        self._save_state()
        return True

    def get_worker_stats(self, worker_name: str, days: int = 7) -> dict[str, Any]:
        """Historical stats for a worker: processed/hr, error rate, avg latency."""
        instance = self._instances.get(worker_name)
        all_workers = {w["name"] for w in self.list_workers()}

        if worker_name not in all_workers and instance is None:
            return {"error": f"Worker '{worker_name}' not found", "name": worker_name}

        processed = self._processed_counts.get(worker_name, 0)
        errors = self._error_counts.get(worker_name, 0)
        error_rate = (errors / processed * 100) if processed > 0 else 0.0

        latencies = self._latency_buckets.get(worker_name, [])
        avg_latency = (sum(latencies) / len(latencies)) if latencies else None
        max_latency = max(latencies) if latencies else None
        p95_latency = _percentile(sorted(latencies), 95) if latencies else None

        # Estimate processed per hour based on registered state
        registered_at = self._state.get(worker_name, {}).get("registered_at")
        hours_running = None
        if registered_at:
            try:
                dt = datetime.fromisoformat(registered_at)
                hours_running = max((datetime.now(UTC) - dt).total_seconds() / 3600, 1 / 3600)
            except Exception:
                pass

        per_hour = round(processed / hours_running, 2) if hours_running else None

        result = {
            "worker": worker_name,
            "label": _worker_label(worker_name),
            "stats_period_days": days,
            "total_processed": processed,
            "total_errors": errors,
            "error_rate_pct": round(error_rate, 2),
            "avg_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
            "max_latency_ms": round(max_latency, 2) if max_latency is not None else None,
            "p95_latency_ms": round(p95_latency, 2) if p95_latency is not None else None,
            "processed_per_hour": per_hour,
            "paused": worker_name in self._paused,
            "running": worker_name in self._instances,
            "registered_at": registered_at,
        }

        if instance is not None:
            result["current_events_processed"] = instance._events_processed

        return result

    def get_queue_stats(self) -> dict[str, Any]:
        """Overall queue / dashboard stats for all workers."""
        workers = self.list_workers()
        total_processed = 0
        total_errors = 0
        running_count = 0
        paused_count = 0

        for w in workers:
            total_processed += w.get("events_processed", 0)
            total_errors += w.get("error_count", 0)
            if w.get("running"):
                running_count += 1
            if w.get("paused"):
                paused_count += 1

        bus_section: dict[str, Any] = {}
        if self._bus is not None:
            s = self._bus.stats()
            bus_section = {
                "bus_queued": s.queued,
                "bus_processed": s.processed,
                "bus_failed": s.failed,
                "bus_retried": s.retried,
                "bus_dlq_count": s.dlq_count,
            }

        return {
            "total_workers": len(workers),
            "running": running_count,
            "paused": paused_count,
            "total_processed_events": total_processed,
            "total_errors": total_errors,
            "error_rate_pct": round((total_errors / max(total_processed, 1)) * 100, 2),
            "workers": [w.get("name") for w in workers],
            **bus_section,
            "generated_at": _now_iso(),
        }

    # ------------------------------------------------------------------
    # Tracking helpers (called by external code)
    # ------------------------------------------------------------------

    def record_processed(self, worker_name: str, latency_ms: float | None = None) -> None:
        """Increment processed counter and optionally record latency."""
        self._processed_counts[worker_name] += 1
        if latency_ms is not None:
            self._latency_buckets[worker_name].append(latency_ms)
            # Keep only recent 1000 samples
            if len(self._latency_buckets[worker_name]) > 1000:
                self._latency_buckets[worker_name] = self._latency_buckets[worker_name][-1000:]
        self._state.setdefault(worker_name, {})["last_active"] = _now_iso()

    def record_error(self, worker_name: str) -> None:
        """Increment error counter for a worker."""
        self._error_counts[worker_name] += 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dlq_to_dict(dl: DeadLetterEvent) -> dict[str, Any]:
    return {
        "event_type": dl.event_type,
        "handler_name": dl.handler_name,
        "error": dl.error[:200] if dl.error else "",
        "retry_count": dl.retry_count,
        "last_attempt": dl.last_attempt.isoformat() if dl.last_attempt else None,
    }


def _percentile(sorted_data: list[float], p: int) -> float:
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])
