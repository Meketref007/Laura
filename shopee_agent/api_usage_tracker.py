"""Shopee API usage tracker — monitors daily API call volume against rate limits.

Shopee limits: 100 calls/second per app (burst), 50,000 calls/day per shop
(soft limit, varies by tier). Alerts via Telegram when approaching limits.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

DEFAULT_DB_PATH = "reports/api_usage.db"
DEFAULT_DAILY_LIMIT = 50000


def _today() -> str:
    return date.today().isoformat()


class APITracker:
    """Tracks daily API call volume in SQLite and flags approaching limits."""

    def __init__(
        self,
        db_path: str | None = None,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
        warn_pct: float = 0.8,
        alert_pct: float = 0.95,
    ):
        self.db_path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        self.daily_limit = int(daily_limit)
        self.warn_pct = float(warn_pct)
        self.alert_pct = float(alert_pct)
        self._lock = threading.Lock()
        self._warned_dates: set[str] = set()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        date TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        count INTEGER NOT NULL DEFAULT 0,
                        errors INTEGER NOT NULL DEFAULT 0,
                        avg_latency_ms REAL NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_usage_date_endpoint "
                    "ON api_usage(date, endpoint)"
                )
                conn.commit()
            finally:
                conn.close()

    def record(self, endpoint: str, status: int = 200, latency_ms: float = 0.0) -> None:
        now = time.time()
        today = _today()
        is_error = 1 if status == 0 or status >= 400 else 0
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT count, errors, avg_latency_ms FROM api_usage "
                    "WHERE date = ? AND endpoint = ?",
                    (today, endpoint),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO api_usage (ts, date, endpoint, count, errors, avg_latency_ms) "
                        "VALUES (?, ?, ?, 1, ?, ?)",
                        (now, today, endpoint, is_error, float(latency_ms)),
                    )
                else:
                    new_count = int(row["count"]) + 1
                    new_errors = int(row["errors"]) + is_error
                    new_avg = (
                        float(row["avg_latency_ms"]) * int(row["count"]) + float(latency_ms)
                    ) / new_count
                    conn.execute(
                        "UPDATE api_usage SET ts = ?, count = ?, errors = ?, avg_latency_ms = ? "
                        "WHERE date = ? AND endpoint = ?",
                        (now, new_count, new_errors, new_avg, today, endpoint),
                    )
                conn.commit()
            finally:
                conn.close()

    def today_counts(self) -> dict:
        today = _today()
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT endpoint, count, errors FROM api_usage WHERE date = ?",
                    (today,),
                ).fetchall()
            finally:
                conn.close()
        by_endpoint = {str(r["endpoint"]): int(r["count"]) for r in rows}
        return {
            "total": sum(int(r["count"]) for r in rows),
            "by_endpoint": by_endpoint,
            "errors": sum(int(r["errors"]) for r in rows),
        }

    def usage_pct(self) -> float:
        if self.daily_limit <= 0:
            return 0.0
        return self.today_counts()["total"] / self.daily_limit

    def should_warn(self) -> bool:
        """True once per day when usage crosses warn_pct."""
        today = _today()
        if today in self._warned_dates:
            return False
        if self.usage_pct() >= self.warn_pct:
            self._warned_dates.add(today)
            return True
        return False

    def should_alert(self) -> bool:
        return self.usage_pct() >= self.alert_pct

    def reset_alerts(self) -> None:
        with self._lock:
            self._warned_dates.clear()

    def summary(self, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT ts, date, endpoint, count, errors, avg_latency_ms "
                    "FROM api_usage ORDER BY ts DESC, id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]


_TRACKER: APITracker | None = None
_TRACKER_LOCK = threading.Lock()


def get_api_tracker(db_path: str | None = None) -> APITracker:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = APITracker(db_path=db_path)
    return _TRACKER


def check_usage() -> dict:
    """Read today's usage and return status; send a Telegram alert if over threshold."""
    tracker = get_api_tracker()
    counts = tracker.today_counts()
    pct = tracker.usage_pct()
    if pct >= tracker.alert_pct:
        status = "critical"
    elif pct >= tracker.warn_pct:
        status = "warning"
    else:
        status = "ok"

    result = {
        "date": _today(),
        "status": status,
        "total": counts["total"],
        "errors": counts["errors"],
        "daily_limit": tracker.daily_limit,
        "usage_pct": round(pct, 4),
        "by_endpoint": counts["by_endpoint"],
    }

    if status in ("warning", "critical"):
        try:
            from .telegram_narrator import narrador
            narrador.alerta(
                f"Shopee API usage at {pct:.0%} of daily limit "
                f"({counts['total']}/{tracker.daily_limit})",
                "Rate limit monitor",
            )
            result["telegram_alert_sent"] = True
        except Exception:
            result["telegram_alert_sent"] = False

    return result
