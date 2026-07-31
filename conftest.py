"""Root conftest — shared fixtures and pytest configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


@pytest.fixture(autouse=True)
def mock_env():
    """Set minimum environment variables for all tests."""
    os.environ.setdefault("LAURA_LLM_MODEL", "tinyllama")
    os.environ.setdefault("SELLER_CENTER_DRY_RUN", "1")
    os.environ.setdefault("RATING_REPLY_AUTO_SEND", "0")
    os.environ.setdefault("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "test:token")


@pytest.fixture
def mock_ollama():
    """Mock Ollama LLM calls."""
    with patch("shopee_agent.llm_local.LauraOllamaAnalyzer") as mock:
        instance = mock.return_value
        instance.analyze.return_value = {"raw_response": '{"intent": "outro", "confidence": 0.3}'}
        yield instance


@pytest.fixture
def mock_requests():
    """Mock requests.Session."""
    with patch("requests.Session") as mock:
        session = mock.return_value
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.json.return_value = {"ok": True}
        resp.text = ""
        session.post.return_value = resp
        session.get.return_value = resp
        yield session


@pytest.fixture
def tmp_reports_dir(tmp_path):
    """Temporary directory for test reports."""
    d = tmp_path / "reports"
    d.mkdir()
    return d
