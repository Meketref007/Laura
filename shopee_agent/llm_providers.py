"""
Unified LLM abstraction layer supporting Ollama (local), OpenAI (ChatGPT),
and Anthropic (Claude).

Auto-detects available providers, handles automatic fallback, and provides
a single interface for all LLM operations.
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .llm_cache import LLMCache, cache_enabled
from .prompts import get_system_prompt

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    provider: str = "ollama"
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 120
    api_key: str = ""
    api_base: str = ""


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    tokens_used: int
    latency_ms: float
    success: bool
    error: str = ""


# ---------------------------------------------------------------------------
# JSON extraction helper (reused from llm_local)
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
    raw = text.strip()
    if not raw:
        return None

    if "```json" in raw:
        start = raw.find("```json") + len("```json")
        end = raw.find("```", start)
        if end > start:
            candidate = raw[start:end].strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

    if "```" in raw:
        start = raw.find("```") + len("```")
        end = raw.find("```", start)
        if end > start:
            candidate = raw[start:end].strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

    decoder = json.JSONDecoder()
    for start_char in ("{", "["):
        start = raw.find(start_char)
        if start < 0:
            continue
        try:
            obj, _ = decoder.raw_decode(raw[start:])
            if isinstance(obj, dict):
                return obj
            continue
        except Exception:
            continue

    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if 0 <= brace_start < brace_end:
        candidate = raw[brace_start:brace_end + 1]
        candidate = re.sub(r",\s*}", "}", candidate)
        candidate = re.sub(r",\s*\]", "]", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Abstract base provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], config: LLMConfig) -> LLMResponse:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    def _count_tokens(self, text: str) -> int:
        return len(text.split())


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------

OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"

DEFAULT_MODELS = {
    "ollama": "llama3.2:3b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
}


class OllamaProvider(LLMProvider):
    def __init__(self, api_base: str = ""):
        self.api_base = api_base or os.getenv("LAURA_OLLAMA_HOST", OLLAMA_DEFAULT_HOST)
        self._requests = None

    @property
    def _requests_lib(self):
        if self._requests is None:
            import requests as r
            self._requests = r
        return self._requests

    def is_available(self) -> bool:
        try:
            resp = self._requests_lib.get(
                f"{self.api_base}/api/tags", timeout=5
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _resolve_model(self, model: str) -> str:
        if model:
            return model
        return os.getenv("LAURA_LLM_MODEL", DEFAULT_MODELS["ollama"])

    def chat(self, messages: list[dict], config: LLMConfig) -> LLMResponse:
        start = time.time()
        model = self._resolve_model(config.model)
        req = self._requests_lib

        system_text = ""
        user_text = ""
        for m in messages:
            if m.get("role") == "system":
                system_text += m.get("content", "") + "\n"
            else:
                user_text += m.get("content", "") + "\n"

        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_text.strip()},
                    {"role": "user", "content": user_text.strip()},
                ],
                "stream": False,
                "options": {
                    "temperature": config.temperature,
                    "num_predict": config.max_tokens,
                },
            }
            resp = req.post(
                f"{self.api_base}/api/chat",
                json=payload,
                timeout=config.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("message", {}).get("content", "")

            elapsed = (time.time() - start) * 1000
            return LLMResponse(
                text=text,
                model=model,
                provider="ollama",
                tokens_used=data.get("eval_count", 0),
                latency_ms=elapsed,
                success=True,
            )
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            return LLMResponse(
                text="",
                model=model,
                provider="ollama",
                tokens_used=0,
                latency_ms=elapsed,
                success=False,
                error=str(exc),
            )

    def list_models(self) -> list[str]:
        try:
            resp = self._requests_lib.get(
                f"{self.api_base}/api/tags", timeout=5
            )
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str = "", api_base: str = ""):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.api_base = api_base or ""
        self._client = None

    @property
    def _client_lib(self):
        if self._client is None:
            from openai import OpenAI
            kwargs = {"api_key": self.api_key}
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = OpenAI(**kwargs)
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _resolve_model(self, model: str) -> str:
        return model or DEFAULT_MODELS["openai"]

    def chat(self, messages: list[dict], config: LLMConfig) -> LLMResponse:
        start = time.time()
        model = self._resolve_model(config.model)
        try:
            client = self._client_lib
            formatted = []
            for m in messages:
                formatted.append({
                    "role": m.get("role", "user"),
                    "content": m.get("content", ""),
                })
            response = client.chat.completions.create(
                model=model,
                messages=formatted,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=config.timeout,
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            total_tokens = (usage.total_tokens if usage else 0)

            elapsed = (time.time() - start) * 1000
            return LLMResponse(
                text=text,
                model=model,
                provider="openai",
                tokens_used=total_tokens,
                latency_ms=elapsed,
                success=True,
            )
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            return LLMResponse(
                text="",
                model=model,
                provider="openai",
                tokens_used=0,
                latency_ms=elapsed,
                success=False,
                error=str(exc),
            )

    def list_models(self) -> list[str]:
        try:
            client = self._client_lib
            models = client.models.list()
            return [m.id for m in models]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client = None

    @property
    def _client_lib(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        if os.getenv("LAURA_ALLOW_PAID_LLM", "0") != "1":
            return False
        return True

    def _resolve_model(self, model: str) -> str:
        return model or DEFAULT_MODELS["anthropic"]

    def chat(self, messages: list[dict], config: LLMConfig) -> LLMResponse:
        start = time.time()
        model = self._resolve_model(config.model)
        try:
            client = self._client_lib

            system_text = ""
            user_messages = []
            for m in messages:
                if m.get("role") == "system":
                    system_text += m.get("content", "") + "\n"
                else:
                    user_messages.append({
                        "role": m.get("role", "user"),
                        "content": m.get("content", ""),
                    })

            if not user_messages:
                user_messages = [{"role": "user", "content": ""}]

            kwargs = {
                "model": model,
                "max_tokens": config.max_tokens,
                "messages": user_messages,
            }

            if system_text.strip():
                kwargs["system"] = [{"type": "text", "text": system_text.strip()}]

            response = client.messages.create(**kwargs)

            text = response.content[0].text if response.content else ""
            total_tokens = response.usage.output_tokens + response.usage.input_tokens

            elapsed = (time.time() - start) * 1000
            return LLMResponse(
                text=text,
                model=model,
                provider="anthropic",
                tokens_used=total_tokens,
                latency_ms=elapsed,
                success=True,
            )
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            return LLMResponse(
                text="",
                model=model,
                provider="anthropic",
                tokens_used=0,
                latency_ms=elapsed,
                success=False,
                error=str(exc),
            )

    def list_models(self) -> list[str]:
        try:
            client = self._client_lib
            models = client.models.list()
            return [m.id for m in models]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}

PROVIDER_AVAILABILITY: dict[str, bool] = {}


def _check_provider_available(name: str) -> bool:
    if name in PROVIDER_AVAILABILITY:
        return PROVIDER_AVAILABILITY[name]
    cls = PROVIDER_REGISTRY.get(name)
    if cls is None:
        return False
    try:
        inst = cls()
        avail = inst.is_available()
    except Exception:
        avail = False
    PROVIDER_AVAILABILITY[name] = avail
    return avail


def _get_available_providers() -> list[str]:
    return [name for name in PROVIDER_REGISTRY if _check_provider_available(name)]


# ---------------------------------------------------------------------------
# LLMEngine – main interface
# ---------------------------------------------------------------------------


class LLMEngine:
    """Main interface for all LLM operations.

    Responses are cached per (provider, model, prompt_type, prompt) when the
    ``LAURA_LLM_CACHE`` env var is enabled (default) — see ``llm_cache``.
    """

    def __init__(self, config: LLMConfig | None = None):
        self._config = config or LLMConfig()
        self._fallback_order = ["ollama", "openai", "anthropic"]
        self._providers: dict[str, LLMProvider] = {}
        self._active_provider_name: str = ""
        self._cache = LLMCache()
        self._init_providers()

    def _init_providers(self) -> None:
        self._providers = {}
        for name, cls in PROVIDER_REGISTRY.items():
            try:
                inst = cls()
                self._providers[name] = inst
            except Exception:
                pass

        available = self._get_available_providers()

        configured = self._config.provider
        if configured and configured != "auto":
            if configured in self._providers and configured in available:
                self._active_provider_name = configured
                return

        for name in self._fallback_order:
            if name in self._providers and name in available:
                self._active_provider_name = name
                return

        if self._providers:
            self._active_provider_name = next(iter(self._providers))
        else:
            self._active_provider_name = ""

    def _get_available_providers(self) -> list[str]:
        result = []
        for name, prov in self._providers.items():
            try:
                if prov.is_available():
                    result.append(name)
            except Exception:
                continue
        return result

    def chat(
        self,
        messages: list[dict],
        config: LLMConfig | None = None,
        prompt_type: str = "general",
    ) -> LLMResponse:
        cfg = config or self._config
        prompt_text = self._messages_to_prompt(messages)

        if cfg.provider and cfg.provider != "auto":
            prov = self._providers.get(cfg.provider)
            if prov is None:
                return self._make_error(f"Provider '{cfg.provider}' not found")
            return self._cached_call(cfg.provider, prov, messages, cfg, prompt_type, prompt_text)

        errors = []
        for name in self._fallback_order:
            prov = self._providers.get(name)
            if prov is None:
                continue
            try:
                if not prov.is_available():
                    errors.append(f"{name}: not available")
                    continue
            except Exception as e:
                errors.append(f"{name}: availability check failed ({e})")
                continue

            result = self._cached_call(name, prov, messages, cfg, prompt_type, prompt_text)
            if result.success:
                return result
            errors.append(f"{name}: {result.error}")

        return LLMResponse(
            text="",
            model="",
            provider="auto",
            tokens_used=0,
            latency_ms=0,
            success=False,
            error="All providers failed: " + "; ".join(errors),
        )

    def analyze(self, prompt_type: str, context: dict, config: LLMConfig | None = None) -> dict:
        system_prompt = get_system_prompt(prompt_type)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, indent=2)},
        ]
        cfg = config or self._config
        response = self.chat(messages, cfg, prompt_type=prompt_type)

        if not response.success:
            return {
                "success": False,
                "error": response.error,
                "provider": response.provider,
                "model": response.model,
                "latency_ms": response.latency_ms,
            }

        parsed = extract_json(response.text)
        if parsed is None:
            return {
                "success": False,
                "error": "Failed to parse JSON from LLM response",
                "raw_response": response.text[:500],
                "provider": response.provider,
                "model": response.model,
                "latency_ms": response.latency_ms,
            }

        parsed["_llm"] = {
            "provider": response.provider,
            "model": response.model,
            "tokens_used": response.tokens_used,
            "latency_ms": response.latency_ms,
        }
        return parsed

    def switch_provider(self, provider: str) -> bool:
        if provider not in self._providers:
            return False
        try:
            if self._providers[provider].is_available():
                self._active_provider_name = provider
                return True
        except Exception:
            pass
        return False

    def get_available_providers(self) -> list[str]:
        return _get_available_providers()

    def get_active_provider(self) -> str:
        return self._active_provider_name or "none"

    def get_provider_models(self, provider: str) -> list[str]:
        prov = self._providers.get(provider)
        if prov is None:
            return []
        if hasattr(prov, "list_models"):
            try:
                return prov.list_models()
            except Exception:
                pass
        return []

    def set_fallback_order(self, providers: list[str]) -> None:
        valid = [p for p in providers if p in PROVIDER_REGISTRY]
        if valid:
            self._fallback_order = valid

    def _make_error(self, msg: str) -> LLMResponse:
        return LLMResponse(
            text="", model="", provider="",
            tokens_used=0, latency_ms=0,
            success=False, error=msg,
        )

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        return "\n".join(
            f"{m.get('role', '')}: {m.get('content', '')}" for m in messages
        )

    def _resolve_model_name(self, provider_name: str, cfg: LLMConfig) -> str:
        prov = self._providers.get(provider_name)
        if prov is not None and hasattr(prov, "_resolve_model"):
            try:
                return str(prov._resolve_model(cfg.model))
            except Exception:
                pass
        return cfg.model or ""

    def _cached_call(
        self,
        provider_name: str,
        prov: LLMProvider,
        messages: list[dict],
        cfg: LLMConfig,
        prompt_type: str,
        prompt_text: str,
    ) -> LLMResponse:
        """Check the response cache before calling the provider; store after."""
        if not cache_enabled():
            return prov.chat(messages, cfg)

        model = self._resolve_model_name(provider_name, cfg)
        try:
            cached = self._cache.get(provider_name, model, prompt_type, prompt_text)
        except Exception:
            cached = None
        if cached is not None:
            return LLMResponse(
                text=cached,
                model=model,
                provider=provider_name,
                tokens_used=0,
                latency_ms=0,
                success=True,
            )

        result = prov.chat(messages, cfg)
        if result.success:
            try:
                self._cache.put(provider_name, model, prompt_type, prompt_text, result.text)
            except Exception:
                pass
        return result
