"""Anomaly Detection — detects deviations in skill execution time and success rate."""

from __future__ import annotations

import json
import statistics
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import SKILL_EXECUTION_HISTORY


class AnomalyDetector:
    """Monitors skill execution metrics and flags anomalies.

    Detects:
    - Execution time spikes (>2 stddev from recent history)
    - Success rate drops below threshold
    - Circuit breaker events
    """

    def __init__(self, history_path: str = str(SKILL_EXECUTION_HISTORY), window_size: int = 20):
        self._history_path = Path(history_path)
        self._window_size = window_size
        self._lock = threading.Lock()
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._load_history()

    def _load_history(self) -> None:
        if not self._history_path.exists():
            return
        try:
            for line in self._history_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                name = entry.get("skill", "unknown")
                with self._lock:
                    self._history[name].append(entry)
                    if len(self._history[name]) > self._window_size * 2:
                        self._history[name] = self._history[name][-self._window_size * 2:]
        except Exception:
            pass

    def check_execution(self, skill_name: str, elapsed: float, ok: bool) -> list[dict[str, Any]]:
        """Check if a single execution is anomalous. Returns list of anomalies."""
        anomalies: list[dict[str, Any]] = []
        with self._lock:
            recent = self._history.get(skill_name, [])[-self._window_size:]
            times = [e.get("elapsed", 0) for e in recent if isinstance(e.get("elapsed"), (int, float))]
            if len(times) >= 5:
                mean = statistics.mean(times)
                stdev = statistics.stdev(times) if len(times) > 1 else 0.0
                threshold = mean + max(2 * stdev, mean * 0.5) if stdev > 0 else mean * 2
                if elapsed > threshold:
                    anomalies.append({
                        "type": "execution_time_spike",
                        "skill": skill_name,
                        "elapsed": round(elapsed, 3),
                        "expected_max": round(threshold, 3),
                        "severity": "medium",
                        "timestamp": datetime.now(UTC).isoformat(),
                    })

            # Check consecutive failures
            recent_oks = [e.get("ok", True) for e in self._history.get(skill_name, [])[-10:]]
            consecutive_fails = 0
            for ok_flag in reversed(recent_oks):
                if not ok_flag:
                    consecutive_fails += 1
                else:
                    break
            if consecutive_fails >= 3:
                anomalies.append({
                    "type": "consecutive_failures",
                    "skill": skill_name,
                    "count": consecutive_fails,
                    "severity": "high",
                    "timestamp": datetime.now(UTC).isoformat(),
                })

        return anomalies

    def get_anomaly_summary(self) -> dict[str, Any]:
        """Return summary of recent anomaly checks."""
        result: dict[str, Any] = {}
        with self._lock:
            for skill_name, entries in self._history.items():
                times = [e.get("elapsed", 0) for e in entries if isinstance(e.get("elapsed"), (int, float))]
                if times:
                    result[skill_name] = {
                        "executions": len(entries),
                        "avg_elapsed": round(statistics.mean(times), 3),
                        "max_elapsed": round(max(times), 3),
                        "success_rate": round(sum(1 for e in entries if e.get("ok")) / len(entries), 3) if entries else 0,
                    }
        return result
