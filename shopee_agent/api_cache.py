"""Local cache for Shopee API data — re-query at most once per month."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CACHE_DIR = Path("reports/api_cache")
DEFAULT_TTL_DAYS = 30


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_key(name: str) -> str:
    return name.lower().replace(" ", "_").replace("/", "_")


def save(name: str, data: Any, ttl_days: int = DEFAULT_TTL_DAYS) -> Path:
    _ensure_cache_dir()
    path = CACHE_DIR / f"{cache_key(name)}.json"
    payload = {
        "_cached_at": time.time(),
        "_ttl_days": ttl_days,
        "_cached_at_iso": datetime.now(UTC).isoformat(),
        "data": data,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(name: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{cache_key(name)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    cached_at = payload.get("_cached_at", 0)
    ttl_days = payload.get("_ttl_days", DEFAULT_TTL_DAYS)
    age_days = (time.time() - cached_at) / 86400
    if age_days > ttl_days:
        return None
    return payload.get("data")


def age(name: str) -> float | None:
    """Return age in days of cached data, or None if not cached."""
    path = CACHE_DIR / f"{cache_key(name)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    cached_at = payload.get("_cached_at", 0)
    return (time.time() - cached_at) / 86400


def is_fresh(name: str, ttl_days: int = DEFAULT_TTL_DAYS) -> bool:
    entry_age = age(name)
    if entry_age is None:
        return False
    return entry_age <= ttl_days


def invalidate(name: str) -> None:
    path = CACHE_DIR / f"{cache_key(name)}.json"
    if path.exists():
        path.unlink()


def list_cached() -> list[dict[str, Any]]:
    _ensure_cache_dir()
    entries = []
    for path in sorted(CACHE_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached_at = payload.get("_cached_at", 0)
            ttl_days = payload.get("_ttl_days", DEFAULT_TTL_DAYS)
            age_days = (time.time() - cached_at) / 86400 if cached_at else 999
            entries.append({
                "name": path.stem,
                "cached_at": payload.get("_cached_at_iso", ""),
                "age_days": round(age_days, 1),
                "ttl_days": ttl_days,
                "fresh": age_days <= ttl_days,
                "size_bytes": path.stat().st_size,
            })
        except Exception:
            pass
    return entries


def get_or_fetch(
    name: str,
    fetch_fn: Callable[[], Any],
    ttl_days: int = DEFAULT_TTL_DAYS,
    force: bool = False,
) -> Any:
    """Return cached data if fresh, otherwise call fetch_fn() and cache result."""
    if not force:
        existing = load(name)
        if existing is not None:
            return existing
    data = fetch_fn()
    save(name, data, ttl_days=ttl_days)
    return data
