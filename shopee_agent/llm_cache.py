"""LLM response cache — avoids re-querying the LLM for identical requests.

Caches by (provider, model, prompt_type, prompt_hash). Persisted to a JSONL file
with LRU eviction and TTL. Zero external dependencies.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import threading
import time
from pathlib import Path

DEFAULT_CACHE_PATH = "reports/llm_cache.jsonl"
DEFAULT_MAX_ENTRIES = 1000
DEFAULT_TTL_SECONDS = 86400

_ENV_PATH = "LAURA_LLM_CACHE_PATH"
_ENV_ENABLED = "LAURA_LLM_CACHE"
_ENV_MAX = "LAURA_LLM_CACHE_MAX"


def cache_enabled() -> bool:
    """Whether the LLM response cache is enabled (default: enabled)."""
    return os.getenv(_ENV_ENABLED, "1") != "0"


class LLMCache:
    """Thread-safe, JSONL-persisted cache for identical LLM requests."""

    def __init__(
        self,
        path: str | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        env_path = os.getenv(_ENV_PATH)
        if path is None and env_path:
            path = env_path
        env_max = os.getenv(_ENV_MAX)
        if env_max:
            try:
                max_entries = int(env_max)
            except ValueError:
                pass
        self.path = Path(path) if path else Path(DEFAULT_CACHE_PATH)
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0
        self._load()

    def _key(self, provider: str, model: str, prompt_type: str, prompt: str) -> str:
        raw = f"{provider}\x1f{model}\x1f{prompt_type}\x1f{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load(self) -> None:
        with self._lock:
            self._entries = {}
            if not self.path.exists():
                return
            try:
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = entry.get("key")
                    if key and isinstance(entry.get("response"), str):
                        self._entries[key] = entry
            except Exception:
                pass

    def _save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("w", encoding="utf-8") as fh:
                    for entry in self._entries.values():
                        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def _evict_if_needed(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        drop_count = max(1, int(self.max_entries * 0.1))
        ordered = sorted(
            self._entries.values(),
            key=lambda e: float(e.get("last_access", e.get("ts", 0.0))),
        )
        for entry in ordered[:drop_count]:
            self._entries.pop(entry.get("key"), None)

    def get(
        self,
        provider: str,
        model: str,
        prompt_type: str,
        prompt: str,
        max_age: int | None = None,
    ) -> str | None:
        """Return the cached response if fresh, else None."""
        key = self._key(provider, model, prompt_type, prompt)
        max_age = self.ttl_seconds if max_age is None else float(max_age)
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if now - float(entry.get("ts", 0.0)) > max_age:
                self._entries.pop(key, None)
                self._misses += 1
                return None
            entry["last_access"] = now
            self._hits += 1
            return str(entry.get("response", ""))

    def put(
        self,
        provider: str,
        model: str,
        prompt_type: str,
        prompt: str,
        response: str,
    ) -> None:
        """Store a response, evicting the oldest 10% if over max_entries."""
        key = self._key(provider, model, prompt_type, prompt)
        now = time.time()
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                existing["response"] = str(response)
                existing["ts"] = now
                existing["last_access"] = now
            else:
                self._entries[key] = {
                    "key": key,
                    "provider": provider,
                    "model": model,
                    "prompt_type": prompt_type,
                    "response": str(response),
                    "ts": now,
                    "last_access": now,
                }
            self._evict_if_needed()
        self._save()

    def stats(self) -> dict:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._entries),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "path": str(self.path),
            }

    def clear(self, older_than: int | None = None) -> int:
        """Remove entries; returns the number removed.

        With ``older_than`` set, only entries whose timestamp is older than
        ``now - older_than`` are removed. With ``None``, everything is removed.
        """
        now = time.time()
        removed = 0
        with self._lock:
            if older_than is None:
                removed = len(self._entries)
                self._entries.clear()
            else:
                cutoff = now - float(older_than)
                for key, entry in list(self._entries.items()):
                    if float(entry.get("ts", 0.0)) < cutoff:
                        self._entries.pop(key, None)
                        removed += 1
        if removed:
            self._save()
        return removed


def cached_llm_call(fn):
    """Decorator that caches calls keyed by ``provider``/``model``/``prompt_type``/``prompt`` kwargs.

    Works for both sync and async callables.
    """

    cache = LLMCache()
    is_async = asyncio.iscoroutinefunction(fn)

    async def _cached_async(*args, **kwargs):
        provider = kwargs.get("provider", "")
        model = kwargs.get("model", "")
        prompt_type = kwargs.get("prompt_type", "")
        prompt = kwargs.get("prompt", "")
        hit = cache.get(provider, model, prompt_type, prompt)
        if hit is not None:
            return hit
        value = await fn(*args, **kwargs)
        cache.put(provider, model, prompt_type, prompt, value)
        return value

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if is_async:
            return _cached_async(*args, **kwargs)
        provider = kwargs.get("provider", "")
        model = kwargs.get("model", "")
        prompt_type = kwargs.get("prompt_type", "")
        prompt = kwargs.get("prompt", "")
        hit = cache.get(provider, model, prompt_type, prompt)
        if hit is not None:
            return hit
        result = fn(*args, **kwargs)
        cache.put(provider, model, prompt_type, prompt, result)
        return result

    return wrapper
