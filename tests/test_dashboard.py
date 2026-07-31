"""Tests for the FastAPI dashboard app."""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


_TEST_API_KEY = "test-api-key-abc123"


@pytest.fixture
def client():
    os.environ["DASHBOARD_API_KEY"] = _TEST_API_KEY
    with patch.multiple(
        "shopee_agent.dashboard",
        _load_json=MagicMock(return_value={}),
        _load_jsonl=MagicMock(return_value=[]),
        FRONTEND_DIST=MagicMock(),
        REPORTS_DIR=MagicMock(),
        _ab_registry=MagicMock(),
        _ab_automator=MagicMock(),
    ):
        FRONTEND_DIST = MagicMock()
        FRONTEND_DIST.exists = MagicMock(return_value=False)
        import shopee_agent.dashboard as dash_mod
        dash_mod.FRONTEND_DIST = FRONTEND_DIST
        dash_mod.REPORTS_DIR = MagicMock()
        from shopee_agent.dashboard import app
        return TestClient(app)


def _auth_headers():
    return {"Authorization": f"Bearer {_TEST_API_KEY}"}


def test_app_creation(client):
    from shopee_agent.dashboard import app
    assert app is not None


def test_health_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_api_status_endpoint(client):
    with patch("shopee_agent.dashboard._load_json", return_value={"health_score": 95}):
        resp = client.get("/api/health", headers=_auth_headers())
        assert resp.status_code == 200


def test_ws_token_endpoint(client):
    resp = client.get("/api/ws-token", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) > 0

def test_generate_ws_token():
    from shopee_agent.dashboard import generate_ws_token
    with patch("shopee_agent.dashboard._get_ws_secret", return_value="test-secret"):
        token = generate_ws_token()
        assert isinstance(token, str)
        assert len(token) > 0
        parts = token.rsplit(":", 1)
        assert len(parts) == 2


def test_websocket_authenticate():
    from shopee_agent.dashboard import generate_ws_token, websocket_authenticate
    with patch("shopee_agent.dashboard._get_ws_secret", return_value="test-secret"):
        token = generate_ws_token()
        assert websocket_authenticate(token) is True
        assert websocket_authenticate("invalid:token") is False
        assert websocket_authenticate("") is False


def test_get_api_key():
    from shopee_agent.dashboard import _get_api_key
    with patch("shopee_agent.dashboard._load_auth", return_value={"api_key": "test-key-123"}):
        key = _get_api_key()
        assert isinstance(key, str)
        assert len(key) > 0
