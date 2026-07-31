"""Skill sandbox — dry-run, timeout, per-skill circuit breaker, rate limiter, retry, resource profiling."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from shopee_agent.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from shopee_agent.logger import warning

# ── Resource profiling ───────────────────────────────────────────────────────

_skill_profiles: dict[str, dict[str, float]] = {}
_profile_lock = threading.Lock()


def record_profile(skill_name: str, elapsed: float) -> None:
    """Record execution time for a skill (thread-safe)."""
    with _profile_lock:
        prev = _skill_profiles.get(skill_name, {"count": 0, "total_elapsed": 0.0, "max_elapsed": 0.0, "min_elapsed": float("inf")})
        prev["count"] += 1
        prev["total_elapsed"] += elapsed
        prev["max_elapsed"] = max(prev["max_elapsed"], elapsed)
        prev["min_elapsed"] = min(prev["min_elapsed"], elapsed)
        _skill_profiles[skill_name] = prev


def get_profile_summary() -> dict[str, dict[str, float]]:
    """Return profiling data for all skills."""
    with _profile_lock:
        result = {}
        for name, data in _skill_profiles.items():
            result[name] = {
                "count": data["count"],
                "total_elapsed": round(data["total_elapsed"], 3),
                "avg_elapsed": round(data["total_elapsed"] / data["count"], 3) if data["count"] else 0,
                "max_elapsed": round(data["max_elapsed"], 3),
                "min_elapsed": round(data["min_elapsed"], 3) if data["min_elapsed"] != float("inf") else 0,
            }
        return result


def reset_profiles() -> None:
    with _profile_lock:
        _skill_profiles.clear()


class SkillTimeout(Exception):
    pass


class SkillCircuitBreaker(CircuitBreaker):
    """Per-skill circuit breaker that tracks failures."""

    def __init__(
        self,
        skill_name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
    ):
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            timeout_seconds=int(recovery_timeout),
            success_threshold=2,
        )
        super().__init__(name=f"skill_{skill_name}", config=config)


class RateLimiter:
    """Simple sliding-window rate limiter per skill."""

    def __init__(self, max_calls: int = 10, window_seconds: float = 60.0):
        self._max = max_calls
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def allow(self, skill_name: str) -> bool:
        now = time.monotonic()
        window_start = now - self._window
        bucket = self._buckets[skill_name]
        bucket[:] = [t for t in bucket if t > window_start]
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True

    def remaining(self, skill_name: str) -> int:
        now = time.monotonic()
        window_start = now - self._window
        bucket = self._buckets[skill_name]
        bucket[:] = [t for t in bucket if t > window_start]
        return max(0, self._max - len(bucket))


_breakers: dict[str, SkillCircuitBreaker] = {}
_rate_limiter = RateLimiter(max_calls=10, window_seconds=60.0)


def get_breaker(skill_name: str) -> SkillCircuitBreaker:
    if skill_name not in _breakers:
        _breakers[skill_name] = SkillCircuitBreaker(skill_name)
    return _breakers[skill_name]


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


async def _run_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 2,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                warning(f"Retry {attempt+1}/{max_retries} after {delay:.1f}s: {exc}")
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def run_skill_sandbox(
    skill_name: str,
    run_fn: Callable[..., Any],
    *args: Any,
    dry_run: bool = False,
    timeout_seconds: float = 30.0,
    max_retries: int = 0,
    retry_base_delay: float = 1.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a skill with sandbox protections.

    Returns dict with keys: ok, result (or error), elapsed, dry_run, circuit_open, rate_limited.
    """
    breaker = get_breaker(skill_name)

    if breaker.state == CircuitState.OPEN:
        warning(f"Skill '{skill_name}' circuit open, skipping")
        return {"ok": False, "error": "circuit_open", "elapsed": 0.0, "dry_run": dry_run, "circuit_open": True, "rate_limited": False, "retries": 0}

    if not _rate_limiter.allow(skill_name):
        remaining = _rate_limiter.remaining(skill_name)
        warning(f"Skill '{skill_name}' rate limited, {remaining} calls remaining")
        return {"ok": False, "error": "rate_limited", "elapsed": 0.0, "dry_run": dry_run, "circuit_open": False, "rate_limited": True, "retries": 0}

    if dry_run:
        return {"ok": True, "result": "[dry-run] skipped", "elapsed": 0.0, "dry_run": True, "circuit_open": False, "rate_limited": False, "retries": 0}

    start = time.monotonic()
    retries_used = 0
    try:
        if max_retries > 0:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, lambda: _run_retry_wrapper(run_fn, max_retries, retry_base_delay, *args, **kwargs)),
                timeout=timeout_seconds,
            )
        else:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, lambda: run_fn(*args, **kwargs)),
                timeout=timeout_seconds,
            )
        elapsed = time.monotonic() - start
        breaker._record_success()
        record_profile(skill_name, elapsed)
        return {"ok": True, "result": str(result)[:500], "elapsed": round(elapsed, 3), "dry_run": False, "circuit_open": False, "rate_limited": False, "retries": retries_used}
    except TimeoutError:
        elapsed = time.monotonic() - start
        breaker._record_failure()
        record_profile(skill_name, elapsed)
        return {"ok": False, "error": f"timeout after {timeout_seconds}s", "elapsed": round(elapsed, 3), "dry_run": False, "circuit_open": False, "rate_limited": False, "retries": retries_used}
    except Exception as exc:
        elapsed = time.monotonic() - start
        breaker._record_failure()
        record_profile(skill_name, elapsed)
        return {"ok": False, "error": str(exc), "elapsed": round(elapsed, 3), "dry_run": False, "circuit_open": False, "rate_limited": False, "retries": retries_used}


def _run_retry_wrapper(fn: Callable, max_retries: int, base_delay: float, *args, **kwargs):
    import asyncio as _asyncio
    async def _inner():
        return await _run_with_retry(fn, *args, max_retries=max_retries, base_delay=base_delay, **kwargs)
    return _asyncio.run(_inner())
