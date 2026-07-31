"""Persistent learning database — SQLite-backed cost learning with history."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import GOAP_LEARNING_DB


class LearningDB:
    """SQLite store for GOAP learning data.

    Replaces the JSON-based learning with full query, rollback, and history support.
    """

    def __init__(self, db_path: str = str(GOAP_LEARNING_DB)):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS costs (
                    action_name TEXT PRIMARY KEY,
                    current_cost REAL NOT NULL DEFAULT 1.0,
                    base_cost REAL NOT NULL DEFAULT 1.0,
                    executions INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    last_updated TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS cost_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_name TEXT NOT NULL,
                    old_cost REAL NOT NULL,
                    new_cost REAL NOT NULL,
                    success INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_name TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    cost REAL NOT NULL,
                    elapsed_ms REAL NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cost_history_name ON cost_history(action_name);
                CREATE INDEX IF NOT EXISTS idx_action_outcomes_name ON action_outcomes(action_name);
            """)
            conn.commit()

    # ── Cost management ───────────────────────────────────────────────────

    def get_cost(self, action_name: str, default: float = 1.0) -> float:
        with self._lock:
            row = self._get_conn().execute("SELECT current_cost FROM costs WHERE action_name=?", (action_name,)).fetchone()
            return float(row["current_cost"]) if row else default

    def get_all_costs(self) -> dict[str, float]:
        with self._lock:
            rows = self._get_conn().execute("SELECT action_name, current_cost FROM costs").fetchall()
            return {r["action_name"]: float(r["current_cost"]) for r in rows}

    def record_outcome(self, action_name: str, success: bool, cost: float, elapsed_ms: float = 0.0) -> float:
        """Record an outcome and return the new adjusted cost."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT current_cost, base_cost, executions, successes, failures FROM costs WHERE action_name=?", (action_name,)).fetchone()
            if row:
                current = float(row["current_cost"])
                base = float(row["base_cost"])
                execs = int(row["executions"])
                successes = int(row["successes"])
                failures = int(row["failures"])
            else:
                current = cost
                base = cost
                execs = 0
                successes = 0
                failures = 0

            old_cost = current
            if success:
                new_cost = max(base * 0.5, current * 0.9)
                successes += 1
            else:
                new_cost = min(base * 5.0, current * 1.3)
                failures += 1
            new_cost = round(new_cost, 2)

            conn.execute("""
                INSERT OR REPLACE INTO costs (action_name, current_cost, base_cost, executions, successes, failures, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (action_name, new_cost, base, execs + 1, successes, failures,
                  datetime.now(UTC).isoformat()))

            conn.execute("INSERT INTO cost_history (action_name, old_cost, new_cost, success, timestamp) VALUES (?,?,?,?,?)",
                         (action_name, old_cost, new_cost, 1 if success else 0, datetime.now(UTC).isoformat()))

            conn.execute("INSERT INTO action_outcomes (action_name, success, cost, elapsed_ms, timestamp) VALUES (?,?,?,?,?)",
                         (action_name, 1 if success else 0, new_cost, round(elapsed_ms, 2), datetime.now(UTC).isoformat()))
            conn.commit()
            return new_cost

    # ── Rollback ──────────────────────────────────────────────────────────

    def rollback(self, action_name: str, steps: int = 1) -> bool:
        """Rollback the last `steps` cost changes for an action. Returns True if successful."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT id, old_cost, new_cost FROM cost_history WHERE action_name=? ORDER BY id DESC LIMIT ?",
                (action_name, steps)
            ).fetchall()
            if not rows:
                return False
            for row in reversed(rows):
                cost_to_restore = float(row["old_cost"])
                conn.execute("UPDATE costs SET current_cost=? WHERE action_name=?", (cost_to_restore, action_name))
            conn.commit()
            return True

    # ── History ───────────────────────────────────────────────────────────

    def get_history(self, action_name: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._get_conn().execute(
                "SELECT * FROM cost_history WHERE action_name=? ORDER BY id DESC LIMIT ?", (action_name, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_outcomes(self, action_name: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._get_conn().execute(
                "SELECT * FROM action_outcomes WHERE action_name=? ORDER BY id DESC LIMIT ?", (action_name, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, action_name: str) -> dict[str, Any]:
        with self._lock:
            row = self._get_conn().execute("SELECT * FROM costs WHERE action_name=?", (action_name,)).fetchone()
            if not row:
                return {"action_name": action_name, "current_cost": 1.0, "executions": 0}
            return dict(row)

    def export_json(self) -> dict[str, Any]:
        """Export all data as JSON (compatibility with old format)."""
        with self._lock:
            costs = self.get_all_costs()
            return costs

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
