"""Tests for the configuration module."""

import os
import pytest
from unittest.mock import patch

# Prevent .env from polluting test environment
pytestmark = pytest.mark.usefixtures("_no_env_file")


@pytest.fixture
def _no_env_file(monkeypatch):
    monkeypatch.setattr("shopee_agent.config._load_env_file_if_present", lambda: None)


_REQUIRED = ["SHOPEE_PARTNER_ID", "SHOPEE_PARTNER_KEY", "SHOPEE_REDIRECT_URL"]


def _clear_required(monkeypatch):
    for k in _REQUIRED:
        monkeypatch.delenv(k, raising=False)


def test_load_config(monkeypatch):
    _clear_required(monkeypatch)
    monkeypatch.setenv("SHOPEE_PARTNER_ID", "12345")
    monkeypatch.setenv("SHOPEE_PARTNER_KEY", "test-key")
    monkeypatch.setenv("SHOPEE_REDIRECT_URL", "https://example.com/callback")
    from shopee_agent.config import load_config
    cfg = load_config()
    assert cfg.partner_id == 12345
    assert cfg.partner_key == "test-key"
    assert cfg.redirect_url == "https://example.com/callback"


def test_config_defaults(monkeypatch):
    _clear_required(monkeypatch)
    monkeypatch.setenv("SHOPEE_PARTNER_ID", "999")
    monkeypatch.setenv("SHOPEE_PARTNER_KEY", "key")
    monkeypatch.setenv("SHOPEE_REDIRECT_URL", "https://example.com")
    monkeypatch.setenv("SHOPEE_BASE_URL", "https://partner.shopeemobile.com")
    from shopee_agent.config import load_config
    cfg = load_config()
    assert cfg.base_url == "https://partner.shopeemobile.com"
    assert cfg.vector_backend == "memory"
    assert cfg.vector_dim == 128


def test_config_env_overrides(monkeypatch):
    _clear_required(monkeypatch)
    monkeypatch.setenv("SHOPEE_PARTNER_ID", "555")
    monkeypatch.setenv("SHOPEE_PARTNER_KEY", "override-key")
    monkeypatch.setenv("SHOPEE_REDIRECT_URL", "https://override.com")
    monkeypatch.setenv("SHOPEE_BASE_URL", "https://custom.api.com")
    monkeypatch.setenv("LAURA_VECTOR_BACKEND", "annoy")
    monkeypatch.setenv("LAURA_VECTOR_DIM", "256")
    from shopee_agent.config import load_config
    cfg = load_config()
    assert cfg.base_url == "https://custom.api.com"
    assert cfg.vector_backend == "annoy"
    assert cfg.vector_dim == 256


def test_config_error_on_missing(monkeypatch):
    for k in _REQUIRED:
        monkeypatch.delenv(k, raising=False)
    from shopee_agent.config import ConfigError, load_config
    with pytest.raises(ConfigError):
        load_config()
