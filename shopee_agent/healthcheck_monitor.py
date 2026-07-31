"""Healthcheck monitor for Laura — periodic health checks + alerting."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

from shopee_agent.paths import REPORTS_DIR

HISTORY_FILE = REPORTS_DIR / "healthcheck_history.jsonl"
HEALTH_LATEST_FILE = REPORTS_DIR / "laura_health_latest.json"

OLLAMA_URL = "http://127.0.0.1:11434"
DASHBOARD_URL = "http://127.0.0.1:8888"


def _http_reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        import urllib.request

        req = urllib.request.Request(url, method="HEAD")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def _disk_usage(path: str) -> dict[str, Any]:
    try:
        usage = os.statvfs(path) if hasattr(os, "statvfs") else None
        if usage:
            total = usage.f_frsize * usage.f_blocks
            free = usage.f_frsize * usage.f_bfree
            used = total - free
            pct = (used / total) * 100 if total else 0
            return {"total_gb": round(total / 1e9, 2), "free_gb": round(free / 1e9, 2), "used_pct": round(pct, 1)}
    except Exception:
        pass
    return {"total_gb": 0, "free_gb": 0, "used_pct": 0}


def _pending_decisions_count() -> int:
    count = 0
    for f in REPORTS_DIR.glob("pending_decisions*.jsonl"):
        try:
            for line in f.read_text().strip().splitlines():
                if line.strip():
                    count += 1
        except Exception:
            pass
    return count


def _last_cycle_timestamp() -> str | None:
    state_file = REPORTS_DIR / "laura_daemon_state.json"
    try:
        data = json.loads(state_file.read_text())
        return data.get("last_cycle") or data.get("last_cycle_ts")
    except Exception:
        return None


def _memory_usage() -> dict[str, Any]:
    if psutil is not None:
        try:
            mem = psutil.virtual_memory()
            return {"total_gb": round(mem.total / 1e9, 2), "used_gb": round(mem.used / 1e9, 2), "percent": mem.percent}
        except Exception:
            pass
    return {"total_gb": 0, "used_gb": 0, "percent": 0}


def _send_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    if not webhook_url:
        return
    try:
        import urllib.request

        data = json.dumps(payload).encode()
        req = urllib.request.Request(webhook_url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def _send_telegram(message: str) -> None:
    secrets_path = REPORTS_DIR.parent / "secrets" / "telegram_setup.json"
    try:
        secrets = json.loads(secrets_path.read_text())
        bot_token = secrets.get("bot_token") or secrets.get("token")
        chat_id = secrets.get("chat_id")
        if bot_token and chat_id:
            import urllib.request

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = json.dumps({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


class HealthcheckMonitor:
    """Periodic health check runner with alerting and history persistence."""

    def __init__(self, check_interval: int = 60, webhook_url: str = "") -> None:
        self._check_interval = check_interval
        self._webhook_url = webhook_url
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._history: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="healthcheck")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._check_interval + 5)
            self._thread = None

    def check(self) -> dict[str, Any]:
        ollama = _http_reachable(OLLAMA_URL)
        dashboard = _http_reachable(DASHBOARD_URL)
        disk = _disk_usage(str(REPORTS_DIR))
        pending = _pending_decisions_count()
        last_cycle = _last_cycle_timestamp()
        memory = _memory_usage()

        result: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "ollama_reachable": ollama,
            "dashboard_reachable": dashboard,
            "disk_usage": disk,
            "pending_decisions": pending,
            "last_cycle_timestamp": last_cycle,
            "memory_usage": memory,
        }
        return result

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self.check()
                score = self._compute_score(result)
                result["health_score"] = score
                with self._lock:
                    self._history.append(result)
                    self._trim_history()
                self._persist(result)
                self.alert_if_unhealthy(result)
            except Exception:
                pass
            self._stop_event.wait(self._check_interval)

    def alert_if_unhealthy(self, result: dict[str, Any] | None = None, threshold: float = 0.7) -> None:
        if result is None:
            result = self.check()
            score = self._compute_score(result)
            result["health_score"] = score
        score = result.get("health_score", 1.0)
        if score >= threshold:
            return
        ts = result.get("timestamp", datetime.now(UTC).isoformat())
        msg = (
            f"\u26a0\ufe0f *Laura Health Alert*\n"
            f"Score: {score:.2f} (threshold: {threshold})\n"
            f"Time: {ts}\n"
            f"Ollama: {'\u2705' if result.get('ollama_reachable') else '\u274c'}\n"
            f"Dashboard: {'\u2705' if result.get('dashboard_reachable') else '\u274c'}\n"
            f"Disk: {result.get('disk_usage', {}).get('used_pct', '?')}%\n"
            f"Pending: {result.get('pending_decisions', 0)}"
        )
        _send_telegram(msg)
        _send_webhook(self._webhook_url, {"text": msg, "alert": "unhealthy", "score": score})

    def get_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def get_health_score(self) -> float:
        with self._lock:
            if not self._history:
                return 1.0
            return self._history[-1].get("health_score", 1.0)

    def _compute_score(self, result: dict[str, Any]) -> float:
        score = 1.0
        if not result.get("ollama_reachable"):
            score -= 0.3
        if not result.get("dashboard_reachable"):
            score -= 0.2
        disk_pct = result.get("disk_usage", {}).get("used_pct", 0)
        if isinstance(disk_pct, (int, float)):
            if disk_pct > 95:
                score -= 0.2
            elif disk_pct > 85:
                score -= 0.1
        pending = result.get("pending_decisions", 0)
        if isinstance(pending, (int, float)):
            if pending > 100:
                score -= 0.15
            elif pending > 50:
                score -= 0.05
        mem_pct = result.get("memory_usage", {}).get("percent", 0)
        if isinstance(mem_pct, (int, float)):
            if mem_pct > 90:
                score -= 0.15
            elif mem_pct > 80:
                score -= 0.05
        return max(0.0, min(1.0, score))

    def _trim_history(self) -> None:
        max_entries = 10000
        while len(self._history) > max_entries:
            self._history.pop(0)

    def _persist(self, entry: dict[str, Any]) -> None:
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with HISTORY_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            HEALTH_LATEST_FILE.write_text(json.dumps(entry, indent=2, ensure_ascii=False))
        except Exception:
            pass


def run_once() -> dict[str, Any]:
    monitor = HealthcheckMonitor()
    result = monitor.check()
    score = monitor._compute_score(result)
    result["health_score"] = score
    print(json.dumps(result, indent=2, ensure_ascii=False))
    monitor._persist(result)
    return result


if __name__ == "__main__":
    run_once()
