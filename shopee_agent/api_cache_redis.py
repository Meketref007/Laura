"""API cache with Redis backend (fallback to JSON file)."""

from __future__ import annotations

import functools
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shopee_agent.logger import debug, warning

# ── Redis availability ────────────────────────────────────────────────────────

_HAS_REDIS = False
_redis = None
try:
    import redis as _redis_lib

    _redis = _redis_lib
    _HAS_REDIS = True
except ImportError:
    _redis = None
    _HAS_REDIS = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_cache_path() -> Path:
    from shopee_agent.paths import REPORTS_DIR

    return REPORTS_DIR / "api_cache.json"


# ── RedisCache ────────────────────────────────────────────────────────────────


class RedisCache:
    """Cache that tries Redis first, falling back to a JSON file on disk.

    If the ``redis`` package is not installed the file fallback is used
    silently (no import error raised).
    """

    def __init__(
        self,
        redis_url: str = "",
        default_ttl: int = 300,
        file_fallback: str = "",
    ):
        self._default_ttl = default_ttl
        self._file_fallback = Path(file_fallback) if file_fallback else _default_cache_path()
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "")
        self._redis_client: Any = None
        self._hits = 0
        self._misses = 0

        if _HAS_REDIS and self._redis_url:
            try:
                self._redis_client = _redis.from_url(self._redis_url, decode_responses=True)
                self._redis_client.ping()
                debug("RedisCache connected", url=self._redis_url)
            except Exception as exc:
                warning("RedisCache connection failed, using file fallback", error=str(exc)[:100])
                self._redis_client = None

        if self._redis_client is None:
            self._file_fallback.parent.mkdir(parents=True, exist_ok=True)

    # -- Redis ops ---------------------------------------------------------

    def _redis_get(self, key: str) -> Any | None:
        if self._redis_client is None:
            return None
        try:
            raw = self._redis_client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def _redis_set(self, key: str, value: Any, ttl: int) -> bool:
        if self._redis_client is None:
            return False
        try:
            raw = json.dumps(value, ensure_ascii=False)
            self._redis_client.setex(key, ttl, raw)
            return True
        except Exception as exc:
            warning("RedisCache set failed", error=str(exc)[:100])
            return False

    def _redis_delete(self, key: str) -> bool:
        if self._redis_client is None:
            return False
        try:
            return bool(self._redis_client.delete(key))
        except Exception:
            return False

    def _redis_clear(self) -> bool:
        if self._redis_client is None:
            return False
        try:
            self._redis_client.flushdb()
            return True
        except Exception:
            return False

    def _redis_stats(self) -> dict | None:
        if self._redis_client is None:
            return None
        try:
            info = self._redis_client.info()
            return {
                "backend": "redis",
                "redis_version": info.get("redis_version", ""),
                "used_memory_human": info.get("used_memory_human", ""),
                "total_connections_received": info.get("total_connections_received", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0),
            }
        except Exception:
            return None

    # -- File fallback ops --------------------------------------------------

    def _load_file_cache(self) -> dict[str, dict]:
        try:
            if self._file_fallback.exists():
                data = json.loads(self._file_fallback.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save_file_cache(self, data: dict[str, dict]) -> bool:
        try:
            self._file_fallback.parent.mkdir(parents=True, exist_ok=True)
            self._file_fallback.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as exc:
            warning("File cache save failed", error=str(exc)[:100])
            return False

    def _file_get(self, key: str) -> Any | None:
        cache = self._load_file_cache()
        entry = cache.get(key)
        if entry is None:
            return None
        expires_at = entry.get("_expires_at", 0)
        if time.time() > expires_at:
            # Expired — remove it
            cache.pop(key, None)
            self._save_file_cache(cache)
            return None
        return entry.get("data")

    def _file_set(self, key: str, value: Any, ttl: int) -> bool:
        cache = self._load_file_cache()
        cache[key] = {
            "_expires_at": time.time() + ttl,
            "_created_at": time.time(),
            "data": value,
        }
        return self._save_file_cache(cache)

    def _file_delete(self, key: str) -> bool:
        cache = self._load_file_cache()
        existed = key in cache
        cache.pop(key, None)
        self._save_file_cache(cache)
        return existed

    def _file_clear(self) -> bool:
        self._save_file_cache({})
        return True

    def _file_stats(self) -> dict:
        cache = self._load_file_cache()
        now = time.time()
        valid = 0
        expired = 0
        for entry in cache.values():
            if entry.get("_expires_at", 0) > now:
                valid += 1
            else:
                expired += 1
        return {
            "backend": "file",
            "total_keys": len(cache),
            "valid_keys": valid,
            "expired_keys": expired,
            "file_size_bytes": self._file_fallback.stat().st_size if self._file_fallback.exists() else 0,
        }

    # -- Public API ---------------------------------------------------------

    def get(self, key: str) -> Any:
        """Get a value from the cache.

        Tries Redis first; falls back to the JSON file if Redis is unavailable.
        """
        value = self._redis_get(key) if self._redis_client else None
        if value is not None:
            self._hits += 1
            return value

        value = self._file_get(key)
        if value is not None:
            self._hits += 1
            return value

        self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Store a value in the cache with a TTL (seconds).

        Tries Redis first; falls back to the JSON file if Redis is unavailable.
        """
        if self._redis_client:
            if self._redis_set(key, value, ttl):
                return True
        return self._file_set(key, value, ttl)

    def delete(self, key: str) -> bool:
        """Remove a key from the cache."""
        if self._redis_client:
            self._redis_delete(key)
        return self._file_delete(key)

    def clear(self) -> bool:
        """Remove all entries from the cache."""
        if self._redis_client:
            self._redis_clear()
        return self._file_clear()

    def stats(self) -> dict:
        """Return cache statistics (hits, misses, backend info)."""
        backend_stats = {}
        if self._redis_client:
            rs = self._redis_stats()
            if rs:
                backend_stats = rs
        if not backend_stats:
            backend_stats = self._file_stats()
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(self._hits + self._misses, 1), 4),
            **backend_stats,
        }


# ── Decorator ─────────────────────────────────────────────────────────────────


def cached(cache: RedisCache, ttl: int = 300) -> Callable:
    """Decorator that caches the return value of a function.

    The cache key is derived from the function name + JSON-encoded args/kwargs.

    Usage::

        cache = RedisCache()
        @cached(cache, ttl=600)
        def fetch_orders(shop_id: int) -> list[dict]:
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key_parts = [func.__name__]
            if args:
                key_parts.append(json.dumps(args, sort_keys=True, default=str))
            if kwargs:
                key_parts.append(json.dumps(kwargs, sort_keys=True, default=str))
            cache_key = ":".join(key_parts)

            cached_value = cache.get(cache_key)
            if cached_value is not None:
                debug("Cache hit", key=cache_key, func=func.__name__)
                return cached_value

            debug("Cache miss", key=cache_key, func=func.__name__)
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl=ttl)
            return result

        return wrapper

    return decorator


# ── ShopeeClient integration ──────────────────────────────────────────────────


def _cached_request(
    client: Any,
    cache: RedisCache,
    path: str,
    method: str = "GET",
    ttl: int = 300,
    **kwargs: Any,
) -> Any:
    """Make a cached API request via ``ShopeeClient._request``.

    Checks the cache before calling the API. On a cache hit the stored
    response is returned immediately. On a miss the real request is made
    and the result is cached for *ttl* seconds.

    Usage from within ShopeeClient::

        from shopee_agent.api_cache_redis import RedisCache, _cached_request

        cache = RedisCache()
        result = _cached_request(self, cache, "/api/v2/order/get_order_list", ttl=600, payload={...})
    """
    # Build a deterministic cache key from the endpoint path + kwargs
    key_parts = [path, method]
    if kwargs:
        key_parts.append(json.dumps(kwargs, sort_keys=True, default=str))
    cache_key = "shopee:" + ":".join(key_parts)

    cached_value = cache.get(cache_key)
    if cached_value is not None:
        debug("Cached request hit", path=path)
        # Re-wrap into ShopeeResponse for compatibility
        from shopee_agent.client import ShopeeResponse

        return ShopeeResponse(
            status_code=cached_value.get("status_code", 200),
            data=cached_value.get("data", {}),
        )

    debug("Cached request miss", path=path)
    response = client._request(path, method, **kwargs)
    if response.status_code == 200:
        cache.set(
            cache_key,
            {"status_code": response.status_code, "data": response.data},
            ttl=ttl,
        )
    return response
