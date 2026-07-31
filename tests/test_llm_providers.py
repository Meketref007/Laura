from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from shopee_agent.llm_providers import (
    LLMConfig,
    LLMResponse,
    extract_json,
    OllamaProvider,
    OpenAIProvider,
    AnthropicProvider,
    LLMEngine,
    PROVIDER_REGISTRY,
    _get_available_providers,
    _check_provider_available,
)


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig()
        assert cfg.provider == "ollama"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 2048

    def test_custom_config(self):
        cfg = LLMConfig(provider="openai", model="gpt-4", temperature=0.5, max_tokens=4096)
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4"


class TestExtractJson:
    def test_extract_json_plain(self):
        assert extract_json('{"key": "value"}') == {"key": "value"}

    def test_extract_json_markdown(self):
        text = 'Some text\n```json\n{"name": "test", "value": 42}\n```\nmore text'
        assert extract_json(text) == {"name": "test", "value": 42}

    def test_extract_json_with_markdown_no_lang(self):
        text = 'Text\n```\n{"a": 1}\n```\nend'
        assert extract_json(text) == {"a": 1}

    def test_extract_json_empty(self):
        assert extract_json("") is None
        assert extract_json("   ") is None

    def test_extract_json_invalid(self):
        assert extract_json("not json at all") is None

    def test_extract_json_trailing_comma(self):
        result = extract_json('{"a": 1,}')
        assert result == {"a": 1}

    def test_extract_json_nested(self):
        text = '```json\n{"outer": {"inner": [1, 2, 3]}}\n```'
        assert extract_json(text) == {"outer": {"inner": [1, 2, 3]}}


class TestOllamaProvider:
    @pytest.fixture
    def provider(self):
        return OllamaProvider(api_base="http://localhost:11434")

    def test_is_available(self, provider):
        mock_requests = MagicMock()
        mock_requests.get.return_value = MagicMock(status_code=200)
        provider._requests = mock_requests
        assert provider.is_available() is True

    def test_is_available_unreachable(self, provider):
        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("Connection refused")
        provider._requests = mock_requests
        assert provider.is_available() is False

    def test_ollama_provider_available_mock(self, provider):
        mock_requests = MagicMock()
        mock_requests.get.return_value = MagicMock(status_code=200)
        provider._requests = mock_requests
        assert provider.is_available() is True

    def test_chat_success(self, provider):
        mock_requests = MagicMock()
        mock_requests.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "Hello!"}, "eval_count": 5},
        )
        provider._requests = mock_requests
        resp = provider.chat([{"role": "user", "content": "Hi"}], LLMConfig())
        assert resp.success is True
        assert resp.text == "Hello!"
        assert resp.provider == "ollama"

    def test_chat_failure(self, provider):
        mock_requests = MagicMock()
        mock_requests.post.side_effect = Exception("Timeout")
        provider._requests = mock_requests
        resp = provider.chat([{"role": "user", "content": "Hi"}], LLMConfig())
        assert resp.success is False
        assert "Timeout" in resp.error

    def test_list_models(self, provider):
        mock_requests = MagicMock()
        mock_requests.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "tinyllama:latest"}, {"name": "llama2:latest"}]},
        )
        provider._requests = mock_requests
        models = provider.list_models()
        assert len(models) == 2


class TestLLMEngine:
    @patch.dict(os.environ, {}, clear=True)
    def test_init_no_providers_available(self):
        with patch("shopee_agent.llm_providers.PROVIDER_REGISTRY", {}):
            engine = LLMEngine()
            assert engine.get_active_provider() == "none"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True)
    def test_llm_engine_init_with_openai(self):
        with patch("shopee_agent.llm_providers.OpenAIProvider.is_available", return_value=True):
            engine = LLMEngine(config=LLMConfig(provider="auto"))
            assert engine.get_active_provider() in ("ollama", "openai", "anthropic")

    def test_get_available_providers_mock_env(self):
        with patch("shopee_agent.llm_providers._get_available_providers", return_value=["ollama"]):
            with patch("shopee_agent.llm_providers.PROVIDER_REGISTRY", {"ollama": OllamaProvider}):
                engine = LLMEngine(config=LLMConfig(provider="auto"))
                providers = engine.get_available_providers()
                assert "ollama" in providers

    def test_switch_provider(self):
        engine = LLMEngine()
        engine._providers["ollama"] = OllamaProvider()
        engine._providers["ollama"].is_available = MagicMock(return_value=True)
        assert engine.switch_provider("ollama") is True

    def test_switch_provider_invalid(self):
        engine = LLMEngine()
        assert engine.switch_provider("nonexistent") is False

    def test_set_fallback_order(self):
        engine = LLMEngine()
        engine.set_fallback_order(["openai", "anthropic", "ollama"])
        assert engine._fallback_order == ["openai", "anthropic", "ollama"]

    def test_set_fallback_order_invalid(self):
        engine = LLMEngine()
        engine.set_fallback_order(["invalid_provider"])
        assert engine._fallback_order != ["invalid_provider"]

    def test_llm_engine_set_fallback_order(self):
        engine = LLMEngine()
        engine.set_fallback_order(["ollama", "openai"])
        assert engine._fallback_order == ["ollama", "openai"]

    def test_chat_specific_provider(self):
        engine = LLMEngine()
        mock_prov = MagicMock()
        mock_prov.chat.return_value = LLMResponse(text="ok", model="m", provider="test", tokens_used=0, latency_ms=0, success=True)
        engine._providers["test_prov"] = mock_prov
        resp = engine.chat([{"role": "user", "content": "hi"}], LLMConfig(provider="test_prov"))
        assert resp.success is True
        assert resp.text == "ok"

    def test_chat_provider_not_found(self):
        engine = LLMEngine()
        resp = engine.chat([], LLMConfig(provider="ghost"))
        assert resp.success is False

    @patch("shopee_agent.llm_providers.get_system_prompt", return_value="test prompt")
    def test_analyze_parse_success(self, mock_get_prompt):
        engine = LLMEngine()
        with patch.object(engine, "chat") as mock_chat:
            mock_chat.return_value = LLMResponse(
                text='{"result": "success"}',
                model="m", provider="ollama",
                tokens_used=10, latency_ms=50,
                success=True,
            )
            result = engine.analyze("triage", {"key": "val"})
            assert result["result"] == "success"

    @patch("shopee_agent.llm_providers.get_system_prompt", return_value="test prompt")
    def test_analyze_parse_failure(self, mock_get_prompt):
        engine = LLMEngine()
        with patch.object(engine, "chat") as mock_chat:
            mock_chat.return_value = LLMResponse(
                text="not json",
                model="m", provider="ollama",
                tokens_used=5, latency_ms=20,
                success=True,
            )
            result = engine.analyze("triage", {})
            assert "error" in result
