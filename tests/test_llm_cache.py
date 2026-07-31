"""Tests for the LLM response cache (shopee_agent.llm_cache)."""

import asyncio
import time
from unittest.mock import patch

from shopee_agent.llm_cache import LLMCache, cached_llm_call


def test_cache_hit_returns_same(tmp_path):
    cache = LLMCache(path=str(tmp_path / "cache.jsonl"))
    assert cache.get("ollama", "tinyllama", "summary", "hello") is None
    cache.put("ollama", "tinyllama", "summary", "hello", "world")
    assert cache.get("ollama", "tinyllama", "summary", "hello") == "world"
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1


def test_cache_miss_calls_provider(tmp_path):
    from shopee_agent.llm_providers import LLMConfig, LLMEngine, LLMResponse, OllamaProvider

    calls = {"n": 0}

    def fake_chat(messages, config):
        calls["n"] += 1
        return LLMResponse(
            text=f"answer-{calls['n']}",
            model="m", provider="ollama",
            tokens_used=1, latency_ms=1.0, success=True,
        )

    with patch.object(OllamaProvider, "is_available", return_value=True), \
         patch.object(OllamaProvider, "_resolve_model", return_value="m"), \
         patch.object(OllamaProvider, "chat", side_effect=fake_chat):
        engine = LLMEngine(LLMConfig(provider="ollama", model="m"))
        engine._cache = LLMCache(path=str(tmp_path / "cache.jsonl"))
        cfg = LLMConfig(provider="ollama", model="m")
        messages = [{"role": "user", "content": "hello"}]
        r1 = engine.chat(messages, cfg)
        r2 = engine.chat(messages, cfg)
        assert calls["n"] == 1
        assert r1.text == "answer-1"
        assert r2.text == "answer-1"  # served from cache


def test_cache_ttl_expiry(tmp_path):
    cache = LLMCache(path=str(tmp_path / "cache.jsonl"), ttl_seconds=1)
    cache.put("p", "m", "t", "q", "r")
    assert cache.get("p", "m", "t", "q") == "r"
    time.sleep(1.1)
    assert cache.get("p", "m", "t", "q") is None


def test_cache_max_entries_lru(tmp_path):
    cache = LLMCache(path=str(tmp_path / "cache.jsonl"), max_entries=10)
    for i in range(15):
        cache.put("p", "m", "t", f"prompt-{i}", f"resp-{i}")
    assert cache.stats()["size"] == 10
    assert cache.get("p", "m", "t", "prompt-0") is None  # oldest evicted
    assert cache.get("p", "m", "t", "prompt-14") == "resp-14"  # newest kept


def test_cache_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "cache.jsonl")
    c1 = LLMCache(path=path)
    c1.put("ollama", "tinyllama", "summarize", "texto", "resposta")
    c2 = LLMCache(path=path)
    assert c2.get("ollama", "tinyllama", "summarize", "texto") == "resposta"


def test_cached_llm_call_decorator(tmp_path, monkeypatch):
    monkeypatch.setenv("LAURA_LLM_CACHE_PATH", str(tmp_path / "decorator.jsonl"))
    monkeypatch.setenv("LAURA_LLM_CACHE_MAX", "500")
    calls = {"n": 0}

    @cached_llm_call
    def fake_llm(provider="", model="", prompt_type="", prompt=""):
        calls["n"] += 1
        return f"out-{calls['n']}"

    a = fake_llm(provider="ollama", model="m", prompt_type="t", prompt="q")
    b = fake_llm(provider="ollama", model="m", prompt_type="t", prompt="q")
    c = fake_llm(provider="ollama", model="m", prompt_type="t", prompt="other")
    assert a == b == "out-1"
    assert c == "out-2"
    assert calls["n"] == 2

    async def _async_check():
        @cached_llm_call
        async def fake_async_llm(provider="", model="", prompt_type="", prompt=""):
            calls["n"] += 1
            return f"async-{calls['n']}"

        x = await fake_async_llm(provider="x", model="y", prompt_type="z", prompt="w")
        y = await fake_async_llm(provider="x", model="y", prompt_type="z", prompt="w")
        assert x == y == "async-3"
        assert calls["n"] == 3

    asyncio.run(_async_check())
