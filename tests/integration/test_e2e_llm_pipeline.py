"""E2E: LLM provider selection -> chat -> analysis -> decision."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from shopee_agent.llm_providers import (
    LLMEngine,
    LLMConfig,
    LLMResponse,
    OllamaProvider,
    OpenAIProvider,
    AnthropicProvider,
    extract_json,
)


@pytest.fixture(autouse=True)
def _disable_llm_cache(monkeypatch):
    monkeypatch.setenv("LAURA_LLM_CACHE", "0")


@pytest.fixture
def mock_ollama_available():
    with patch.object(OllamaProvider, "is_available", return_value=True) as mock:
        yield mock


@pytest.fixture
def mock_openai_available():
    with patch.object(OpenAIProvider, "is_available", return_value=True) as mock:
        yield mock


@pytest.fixture
def mock_anthropic_available():
    with patch.object(AnthropicProvider, "is_available", return_value=False) as mock:
        yield mock


@pytest.fixture
def llm_config():
    return LLMConfig(provider="auto", model="tinyllama", temperature=0.7, max_tokens=2048)


@pytest.mark.integration
class TestLLMProviderSelection:
    """E2E: Provider auto-selection and fallback."""

    def test_ollama_selected_when_available(self, mock_ollama_available, mock_openai_available, mock_anthropic_available):
        engine = LLMEngine()
        active = engine.get_active_provider()
        assert active == "ollama", f"Expected ollama, got {active}"

    def test_openai_fallback_when_ollama_unavailable(self, mock_openai_available, mock_anthropic_available):
        with patch.object(OllamaProvider, "is_available", return_value=False):
            with patch.object(OpenAIProvider, "is_available", return_value=True):
                engine = LLMEngine()
                active = engine.get_active_provider()
                assert active == "openai", f"Expected openai, got {active}"

    def test_anthropic_fallback_when_ollama_and_openai_unavailable(self, mock_anthropic_available):
        with patch.object(OllamaProvider, "is_available", return_value=False):
            with patch.object(OpenAIProvider, "is_available", return_value=False):
                with patch.object(AnthropicProvider, "is_available", return_value=True):
                    engine = LLMEngine()
                    active = engine.get_active_provider()
                    assert active == "anthropic", f"Expected anthropic, got {active}"

    def test_manual_provider_selection(self):
        with patch.object(OpenAIProvider, "is_available", return_value=True):
            engine = LLMEngine(config=LLMConfig(provider="openai"))
            active = engine.get_active_provider()
            assert active == "openai", "Should select manually configured provider"

    def test_switch_provider(self, mock_ollama_available, mock_openai_available):
        engine = LLMEngine()
        assert engine.get_active_provider() == "ollama"
        ok = engine.switch_provider("openai")
        assert ok is True
        assert engine.get_active_provider() == "openai"

    def test_get_available_providers(self, mock_ollama_available, mock_openai_available):
        engine = LLMEngine()
        available = engine.get_available_providers()
        assert "ollama" in available
        assert "openai" in available


@pytest.mark.integration
class TestLLMChatCompletion:
    """E2E: Chat completion flow with mocked providers."""

    def test_ollama_chat_returns_success(self):
        with patch.object(OllamaProvider, "is_available", return_value=True):
            with patch.object(OllamaProvider, "chat", return_value=LLMResponse(
                text='{"intent": "tracking", "confidence": 0.95}',
                model="tinyllama",
                provider="ollama",
                tokens_used=45,
                latency_ms=1200.0,
                success=True,
            )):
                engine = LLMEngine()
                response = engine.chat([
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Onde esta meu pedido?"},
                ])
                assert response.success is True
                assert response.provider == "ollama"
                assert response.tokens_used == 45
                assert response.latency_ms > 0
                assert "tracking" in response.text

    def test_chat_fallback_on_failure(self, mock_ollama_available, mock_openai_available):
        with patch.object(OllamaProvider, "chat", return_value=LLMResponse(
            text="", model="tinyllama", provider="ollama",
            tokens_used=0, latency_ms=500.0, success=False, error="timeout",
        )):
            with patch.object(OpenAIProvider, "chat", return_value=LLMResponse(
                text='{"intent": "tracking", "confidence": 0.9}',
                model="gpt-4o-mini", provider="openai",
                tokens_used=30, latency_ms=800.0, success=True,
            )):
                engine = LLMEngine(config=LLMConfig(provider="auto"))
                response = engine.chat([
                    {"role": "user", "content": "Onde esta meu pedido?"},
                ])
                assert response.success is True
                assert response.provider == "openai"

    def test_all_providers_fail_returns_error(self, mock_ollama_available, mock_openai_available):
        with patch.object(OllamaProvider, "chat", return_value=LLMResponse(
            text="", model="tinyllama", provider="ollama",
            tokens_used=0, latency_ms=100.0, success=False, error="timeout",
        )):
            with patch.object(OpenAIProvider, "chat", return_value=LLMResponse(
                text="", model="gpt-4o-mini", provider="openai",
                tokens_used=0, latency_ms=200.0, success=False, error="rate_limit",
            )):
                engine = LLMEngine(config=LLMConfig(provider="auto"))
                response = engine.chat([
                    {"role": "user", "content": "test"},
                ])
                assert response.success is False
                assert "All providers failed" in response.error


@pytest.mark.integration
class TestLLMAnalysisAndParsing:
    """E2E: Structured output parsing and error handling."""

    def test_analyze_returns_parsed_json(self):
        with patch.object(OllamaProvider, "is_available", return_value=True):
            with patch.object(OllamaProvider, "chat", return_value=LLMResponse(
                text='{"intent": "cancellation", "confidence": 0.88, "reason": "buyer_request"}',
                model="tinyllama", provider="ollama",
                tokens_used=50, latency_ms=900.0, success=True,
            )):
                engine = LLMEngine()
                result = engine.analyze("general_agent", {"message": "Quero cancelar"})
                assert result.get("success") is not False
                assert result.get("intent") == "cancellation"
                assert result.get("confidence") == 0.88
                assert "_llm" in result
                assert result["_llm"]["provider"] == "ollama"

    def test_analyze_handles_non_json_response(self):
        with patch.object(OllamaProvider, "is_available", return_value=True):
            with patch.object(OllamaProvider, "chat", return_value=LLMResponse(
                text="I don't know what you mean",
                model="tinyllama", provider="ollama",
                tokens_used=10, latency_ms=300.0, success=True,
            )):
                engine = LLMEngine()
                result = engine.analyze("general_agent", {"message": "hi"})
                assert result.get("success") is False
                assert "Failed to parse JSON" in result.get("error", "")

    def test_analyze_returns_error_on_chat_failure(self):
        with patch.object(OllamaProvider, "is_available", return_value=True):
            with patch.object(OllamaProvider, "chat", return_value=LLMResponse(
                text="", model="tinyllama", provider="ollama",
                tokens_used=0, latency_ms=100.0, success=False, error="connection refused",
            )):
                engine = LLMEngine()
                result = engine.analyze("general_agent", {"message": "test"})
                assert result.get("success") is False
                assert "connection refused" in result.get("error", "")

    def test_extract_json_from_markdown_block(self):
        text = 'Here is the result:\n```json\n{"key": "value", "number": 42}\n```\nEnd.'
        result = extract_json(text)
        assert result is not None
        assert result["key"] == "value"
        assert result["number"] == 42

    def test_extract_json_from_bare_braces(self):
        text = 'Some text {"nested": {"a": 1}} trailing'
        result = extract_json(text)
        assert result is not None
        assert result["nested"]["a"] == 1

    def test_extract_json_returns_none_on_invalid(self):
        assert extract_json("") is None
        assert extract_json("no json here") is None
        assert extract_json("just random text without braces") is None


@pytest.mark.integration
class TestLLMErrorHandling:
    """E2E: Error handling and retry scenarios."""

    def test_invalid_provider_name(self):
        engine = LLMEngine(config=LLMConfig(provider="nonexistent"))
        response = engine.chat([{"role": "user", "content": "hi"}])
        assert response.success is False
        assert "not found" in response.error

    def test_set_fallback_order(self, mock_ollama_available, mock_openai_available):
        engine = LLMEngine()
        engine.set_fallback_order(["openai", "ollama"])
        available = engine.get_available_providers()
        assert "openai" in available

    def test_get_provider_models(self):
        with patch.object(OllamaProvider, "is_available", return_value=True):
            with patch.object(OllamaProvider, "list_models", return_value=["tinyllama", "llama2"]):
                engine = LLMEngine()
                models = engine.get_provider_models("ollama")
                assert "tinyllama" in models
