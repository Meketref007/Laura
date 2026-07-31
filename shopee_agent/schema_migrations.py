"""Schema versioning and migration system for Laura's SQLite databases."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from shopee_agent.logger import error, info, warning

MIGRATIONS: list[tuple[int, str, str, str]] = [
    (
        1,
        "Initial schema: learning costs, outcomes, and notes tables",
        """
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
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        """
        DROP TABLE IF EXISTS notes;
        DROP TABLE IF EXISTS action_outcomes;
        DROP TABLE IF EXISTS cost_history;
        DROP TABLE IF EXISTS costs;
        """,
    ),
    (
        2,
        "Add indexes for performance on outcomes and notes tables",
        """
        CREATE INDEX IF NOT EXISTS idx_cost_history_name ON cost_history(action_name);
        CREATE INDEX IF NOT EXISTS idx_cost_history_ts ON cost_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_action_outcomes_name ON action_outcomes(action_name);
        CREATE INDEX IF NOT EXISTS idx_action_outcomes_ts ON action_outcomes(timestamp);
        CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes(tags);
        CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);
        """,
        """
        DROP INDEX IF EXISTS idx_notes_updated;
        DROP INDEX IF EXISTS idx_notes_tags;
        DROP INDEX IF EXISTS idx_action_outcomes_ts;
        DROP INDEX IF EXISTS idx_action_outcomes_name;
        DROP INDEX IF EXISTS idx_cost_history_ts;
        DROP INDEX IF EXISTS idx_cost_history_name;
        """,
    ),
    (
        3,
        "Add webhook events table for tracking incoming webhooks",
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            received_at TEXT NOT NULL,
            processed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_events_type ON webhook_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON webhook_events(status);
        """,
        """
        DROP INDEX IF EXISTS idx_webhook_events_status;
        DROP INDEX IF EXISTS idx_webhook_events_type;
        DROP TABLE IF EXISTS webhook_events;
        """,
    ),
]


class SchemaManager:
    """Manages SQLite schema versioning and migrations."""

    def __init__(self, db_path: str = "reports/laura.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def get_current_version(self) -> int:
        with self._lock:
            conn = self._get_conn()
            try:
                return conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                conn.close()

    def list_migrations(self) -> list[dict[str, Any]]:
        current = self.get_current_version()
        result: list[dict[str, Any]] = []
        for version, description, up_sql, down_sql in MIGRATIONS:
            result.append({
                "version": version,
                "description": description,
                "applied": version <= current,
                "up_sql_len": len(up_sql.strip()),
                "down_sql_len": len(down_sql.strip()),
            })
        return result

    def get_pending_migrations(self) -> list[dict[str, Any]]:
        current = self.get_current_version()
        return [
            m for m in self.list_migrations()
            if not m["applied"] and m["version"] > current
        ]

    def run_migrations(self, target_version: int | None = None) -> list[str]:
        current = self.get_current_version()
        logs: list[str] = []
        pending = [m for m in MIGRATIONS if m[0] > current]
        if target_version is not None:
            pending = [m for m in pending if m[0] <= target_version]

        if not pending:
            msg = f"Schema is up-to-date (version {current}). No migrations to run."
            info(msg)
            logs.append(msg)
            return logs

        for version, description, up_sql, down_sql in pending:
            with self._lock:
                conn = self._get_conn()
                try:
                    conn.execute("BEGIN")
                    conn.executescript(up_sql)
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.commit()
                    msg = f"Migration v{version}: {description} — OK"
                    info(msg)
                    logs.append(msg)
                except Exception as exc:
                    conn.rollback()
                    msg = f"Migration v{version}: {description} — FAILED: {exc}"
                    error(msg)
                    logs.append(msg)
                    break
                finally:
                    conn.close()

        final_ver = self.get_current_version()
        info(f"Schema now at version {final_ver}")
        logs.append(f"Schema now at version {final_ver}")
        return logs

    def rollback(self, steps: int = 1) -> bool:
        current = self.get_current_version()
        if current <= 0 or steps <= 0:
            warning("No migrations to roll back.")
            return False

        target = max(0, current - steps)
        to_rollback = [m for m in MIGRATIONS if m[0] > target and m[0] <= current]
        to_rollback.reverse()

        for version, description, up_sql, down_sql in to_rollback:
            with self._lock:
                conn = self._get_conn()
                try:
                    conn.execute("BEGIN")
                    conn.executescript(down_sql)
                    conn.execute(f"PRAGMA user_version = {version - 1}")
                    conn.commit()
                    info(f"Rollback v{version}: {description} — OK")
                except Exception as exc:
                    conn.rollback()
                    error(f"Rollback v{version}: {description} — FAILED: {exc}")
                    return False
                finally:
                    conn.close()

        info(f"Rolled back to version {self.get_current_version()}")
        return True


def handle_db_version(args: Any) -> None:
    mgr = SchemaManager(db_path=args.db_path)
    ver = mgr.get_current_version()
    print(f"Current schema version: {ver}")
    pending = mgr.get_pending_migrations()
    if pending:
        print(f"Pending migrations: {len(pending)}")
        for m in pending:
            print(f"  v{m['version']}: {m['description']}")
    else:
        print("Schema is up-to-date.")


def handle_db_migrate(args: Any) -> None:
    mgr = SchemaManager(db_path=args.db_path)
    logs = mgr.run_migrations()
    for line in logs:
        print(line)


def handle_db_rollback(args: Any) -> None:
    mgr = SchemaManager(db_path=args.db_path)
    ok = mgr.rollback(steps=args.steps)
    if ok:
        print(f"Rolled back {args.steps} step(s). Current version: {mgr.get_current_version()}")
    else:
        print("Rollback failed or nothing to roll back.")


def handle_db_list(args: Any) -> None:
    mgr = SchemaManager(db_path=args.db_path)
    migrations = mgr.list_migrations()
    print(f"{'Version':<8} {'Applied':<8} Description")
    print("-" * 60)
    for m in migrations:
        status = "YES" if m["applied"] else "-"
        print(f"v{m['version']:<6} {status:<8} {m['description']}")


def build_parser(subparsers) -> None:
    db_parser = subparsers.add_parser("db", help="Schema versioning and migration management")
    db_parser.add_argument("--db-path", default="reports/laura.db", help="Path to SQLite database")
    db_sub = db_parser.add_subparsers(dest="db_action", required=True)

    db_sub.add_parser("version", help="Show current schema version")
    db_sub.add_parser("migrate", help="Run pending migrations")
    db_rollback = db_sub.add_parser("rollback", help="Rollback N migrations")
    db_rollback.add_argument("--steps", type=int, default=1, help="Number of steps to roll back")
    db_sub.add_parser("list", help="List all migrations with status")
