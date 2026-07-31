"""PlanStore — persist plans to SQLite for audit, replay, and analysis."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import PLAN_STORE_DB


def diff_plans(
    plan_a: dict[str, Any],
    plan_b: dict[str, Any],
) -> dict[str, Any]:
    """Compare two plans and return differences."""
    actions_a = set(plan_a.get("actions", []))
    actions_b = set(plan_b.get("actions", []))
    only_a = list(actions_a - actions_b)
    only_b = list(actions_b - actions_a)
    common = list(actions_a & actions_b)
    cost_a = plan_a.get("total_cost", 0)
    cost_b = plan_b.get("total_cost", 0)
    return {
        "plan_a_id": plan_a.get("id"),
        "plan_b_id": plan_b.get("id"),
        "actions_only_a": only_a,
        "actions_only_b": only_b,
        "actions_common": common,
        "cost_a": cost_a,
        "cost_b": cost_b,
        "cost_diff": round(cost_b - cost_a, 2),
        "num_actions_a": len(actions_a),
        "num_actions_b": len(actions_b),
        "start_state_a": plan_a.get("start_state"),
        "goal_a": plan_a.get("goal"),
    }


def export_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Serialize a plan to a portable JSON dict (no internal IDs)."""
    return {
        "version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "plan_hash": plan.get("plan_hash"),
        "start_state": plan.get("start_state"),
        "goal": plan.get("goal"),
        "actions": plan.get("actions"),
        "total_cost": plan.get("total_cost"),
        "max_depth": plan.get("max_depth"),
        "max_budget": plan.get("max_budget"),
    }


def import_plan(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize an imported plan dict for PlanStore.save_plan()."""
    return {
        "plan_hash": data.get("plan_hash", ""),
        "start_state": data.get("start_state", {}),
        "goal": data.get("goal", {}),
        "actions": data.get("actions", []),
        "total_cost": float(data.get("total_cost", 0)),
        "max_depth": int(data.get("max_depth", 6)),
        "max_budget": data.get("max_budget"),
    }


class PlanStore:
    """Persists GOAP plans to SQLite with full state snapshots.

    Each plan record stores: start_state, goal, actions, cost, outcome, timestamps.
    """

    def __init__(self, db_path: str = str(PLAN_STORE_DB)):
        self._path = db_path if db_path == ":memory:" else Path(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_hash TEXT NOT NULL,
                    start_state TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    actions TEXT NOT NULL,
                    total_cost REAL NOT NULL,
                    max_depth INTEGER NOT NULL DEFAULT 6,
                    max_budget REAL,
                    all_ok INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plans_hash ON plans(plan_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plans_created ON plans(created_at)
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            db_path_str = ":memory:" if self._path == ":memory:" else str(self._path)
            self._conn = sqlite3.connect(db_path_str, check_same_thread=False)
        return self._conn

    def save_plan(
        self,
        plan_hash: str,
        start_state: dict[str, Any],
        goal: dict[str, Any],
        actions: list[str],
        total_cost: float,
        max_depth: int = 6,
        max_budget: float | None = None,
        all_ok: bool = False,
    ) -> int:
        """Save a plan and return its id."""
        with self._lock:
            conn = self._connect()
            now = datetime.now(UTC).isoformat()
            cur = conn.execute(
                """INSERT INTO plans
                   (plan_hash, start_state, goal, actions, total_cost, max_depth, max_budget, all_ok, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan_hash,
                    json.dumps(start_state, ensure_ascii=False),
                    json.dumps(goal, ensure_ascii=False),
                    json.dumps(actions, ensure_ascii=False),
                    total_cost,
                    max_depth,
                    max_budget,
                    1 if all_ok else 0,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0

    def mark_executed(self, plan_id: int, all_ok: bool, error: str = "") -> None:
        """Mark a plan as executed with outcome."""
        with self._lock:
            conn = self._connect()
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE plans SET executed_at = ?, all_ok = ?, error = ? WHERE id = ?",
                (now, 1 if all_ok else 0, error[:500], plan_id),
            )
            conn.commit()

    def get_plan(self, plan_id: int) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM plans ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_by_hash(self, plan_hash: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM plans WHERE plan_hash = ? ORDER BY created_at DESC", (plan_hash,)
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM plans WHERE all_ok = 1").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM plans WHERE all_ok = 0 AND executed_at IS NOT NULL").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM plans WHERE executed_at IS NULL").fetchone()[0]
            avg_cost = conn.execute("SELECT AVG(total_cost) FROM plans").fetchone()[0] or 0.0
            return {
                "total_plans": total,
                "successful": success,
                "failed": failed,
                "pending_execution": pending,
                "avg_cost": round(avg_cost, 2),
            }

    def export_plan_to_json(self, plan_id: int) -> dict[str, Any] | None:
        """Export a plan as portable JSON."""
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        return export_plan(plan)

    def import_plan_from_json(self, data: dict[str, Any]) -> int:
        """Import a plan from portable JSON. Returns new plan id."""
        normalized = import_plan(data)
        return self.save_plan(**normalized)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row[0],
            "plan_hash": row[1],
            "start_state": json.loads(row[2]) if isinstance(row[2], str) else row[2],
            "goal": json.loads(row[3]) if isinstance(row[3], str) else row[3],
            "actions": json.loads(row[4]) if isinstance(row[4], str) else row[4],
            "total_cost": row[5],
            "max_depth": row[6],
            "max_budget": row[7],
            "all_ok": bool(row[8]),
            "created_at": row[9],
            "executed_at": row[10],
            "error": row[11],
        }
