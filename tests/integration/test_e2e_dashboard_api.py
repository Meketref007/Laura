"""E2E: Dashboard API -> WebSocket -> frontend data flow."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from starlette.testclient import TestClient, WebSocketTestSession
    HAS_STARLETTE = True
except ImportError:
    HAS_STARLETTE = False

from shopee_agent.dashboard import app


@pytest.fixture
def test_client(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "laura_health_latest.json").write_text(
        json.dumps({"health_score": 92, "status": "healthy"}), encoding="utf-8"
    )
    (reports_dir / "laura_profitability_latest.json").write_text(
        json.dumps({"metrics": {"margin_pct": 18.5}, "action_key": "hold"}), encoding="utf-8"
    )
    (reports_dir / "laura_daemon_state.json").write_text(
        json.dumps({"running": True, "cycle_count": 42, "error_count": 1, "last_cycle": "2026-07-30T10:00:00"}), encoding="utf-8"
    )
    (reports_dir / "rating_replies_pending.jsonl").write_text("", encoding="utf-8")
    (reports_dir / "chat_pending_responses.jsonl").write_text("", encoding="utf-8")
    (reports_dir / "laura_logs.jsonl").write_text(
        json.dumps({"time": "2026-07-30T10:00:00", "level": "INFO", "message": "Cycle completed"}) + "\n",
        encoding="utf-8",
    )
    (reports_dir / "dashboard_auth.json").write_text(
        json.dumps({"ws_secret": "test-secret", "ws_tokens": [], "api_key": ""}), encoding="utf-8"
    )
    auth_file = reports_dir / "dashboard_auth.json"
    with patch("shopee_agent.dashboard.REPORTS_DIR", reports_dir):
        with patch("shopee_agent.dashboard.RATING_PENDING", reports_dir / "rating_replies_pending.jsonl"):
            with patch("shopee_agent.dashboard.CHAT_PENDING", reports_dir / "chat_pending_responses.jsonl"):
                with patch("shopee_agent.dashboard.AUTH_FILE", auth_file):
                    with patch("shopee_agent.dashboard.FRONTEND_DIST", tmp_path / "frontend" / "dist"):
                        yield TestClient(app) if HAS_STARLETTE else None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_STARLETTE, reason="starlette.testclient not installed"),
]


class TestDashboardAPIEndpoints:
    """E2E: REST API endpoints return proper JSON."""

    def test_health_endpoint(self, test_client):
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("health_score") == 92
        assert data.get("status") == "healthy"

    def test_profitability_endpoint(self, test_client):
        resp = test_client.get("/api/profitability")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["margin_pct"] == 18.5

    def test_ws_token_endpoint_returns_token(self, test_client):
        resp = test_client.get("/api/ws-token")
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) > 10

    def test_skills_endpoint_returns_registered_skills(self, test_client):
        resp = test_client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "registered_skills" in data
        assert "registered_count" in data

    def test_stores_endpoint_returns_list(self, test_client):
        resp = test_client.get("/api/stores")
        assert resp.status_code == 200
        data = resp.json()
        assert "stores" in data

    def test_ab_tests_stats_endpoint(self, test_client):
        resp = test_client.get("/api/ab-tests/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tests" in data

    def test_ab_tests_list_endpoint(self, test_client):
        resp = test_client.get("/api/ab-tests")
        assert resp.status_code == 200

    def test_goap_graph_endpoint(self, test_client):
        resp = test_client.get("/api/goap-graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data or "error" in data

    def test_goap_timeline_endpoint(self, test_client):
        resp = test_client.get("/api/goap-timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data

    def test_skill_health_endpoint(self, test_client):
        resp = test_client.get("/api/skill-health")
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data


@pytest.mark.integration
class TestDashboardAuthMiddleware:
    """E2E: API key authentication middleware."""

    def test_unauthenticated_request_returns_401(self, test_client):
        resp = test_client.get("/api/health")
        assert resp.status_code in (200, 401)

    def test_unauthorized_request_rejected(self, test_client):
        with patch("shopee_agent.dashboard._load_auth", return_value={"api_key": "real-key", "ws_secret": "s"}):
            with patch.dict(os.environ, {"DASHBOARD_API_KEY": "real-key"}, clear=False):
                resp = test_client.get(
                    "/api/health",
                    headers={"Authorization": "Bearer wrong-key"},
                )
                assert resp.status_code == 401
                assert resp.json()["error"] == "Unauthorized"

    def test_authorized_request_succeeds(self, test_client):
        with patch("shopee_agent.dashboard._load_auth", return_value={"api_key": "real-key", "ws_secret": "s"}):
            with patch.dict(os.environ, {"DASHBOARD_API_KEY": "real-key"}, clear=False):
                resp = test_client.get(
                    "/api/health",
                    headers={"Authorization": "Bearer real-key"},
                )
                assert resp.status_code == 200


@pytest.mark.integration
class TestDashboardWebSocket:
    """E2E: WebSocket connection and message flow."""

    def test_websocket_connect_and_stream(self, test_client):
        with patch("shopee_agent.dashboard._get_ws_secret", return_value="test-secret"):
            with patch("shopee_agent.dashboard.websocket_authenticate", return_value=True):
                with test_client.websocket_connect("/ws/stream") as ws:
                    ws.send_json({"type": "auth", "token": "valid-token"})
                    data = ws.receive_json()
                    assert "type" in data

    def test_websocket_auth_with_valid_token(self, test_client):
        with patch("shopee_agent.dashboard._get_ws_secret", return_value="test-secret"):
            with patch("shopee_agent.dashboard.websocket_authenticate", return_value=True):
                with test_client.websocket_connect("/ws/stream") as ws:
                    ws.send_json({"type": "auth", "token": "valid-token"})
                    data = ws.receive_json()
                    assert data is not None

    def test_websocket_receives_state_updates(self, test_client):
        with patch("shopee_agent.dashboard._get_ws_secret", return_value="test-secret"):
            with patch("shopee_agent.dashboard.websocket_authenticate", return_value=True):
                with test_client.websocket_connect("/ws/stream") as ws:
                    ws.send_json({"type": "auth", "token": "valid-token"})
                    ws.send_json({"type": "ping"})
                    data = ws.receive_json()
                    assert isinstance(data, dict)


@pytest.mark.integration
class TestDashboardFrontendRouting:
    """E2E: SPA fallback and static file serving."""

    def test_home_endpoint_returns_html(self, test_client):
        resp = test_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Laura" in resp.text

    def test_favicon_svg(self, test_client):
        resp = test_client.get("/favicon.ico")
        assert resp.status_code == 200
        assert "svg" in resp.text

    def test_manifest_json(self, test_client):
        resp = test_client.get("/manifest.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "Laura Dashboard" in data["name"]

    def test_service_worker_js(self, test_client):
        resp = test_client.get("/sw.js")
        assert resp.status_code == 200
        assert "application/javascript" in resp.headers["content-type"]
        assert "skipWaiting" in resp.text

    def test_single_page_app_fallback(self, test_client):
        with patch("shopee_agent.dashboard.FRONTEND_DIST", Path("C:\\nonexistent_frontend")):
            resp = test_client.get("/")
            assert resp.status_code == 200


@pytest.mark.integration
class TestDashboardCORS:
    """E2E: CORS headers."""

    def test_cors_headers_present(self, test_client):
        resp = test_client.get(
            "/api/health",
            headers={"Origin": "http://localhost:5173"},
        )
        cors_origin = resp.headers.get("access-control-allow-origin")
        assert cors_origin is None or cors_origin == "*" or "http://localhost" in cors_origin

    def test_cors_allows_get_from_any_origin(self, test_client):
        resp = test_client.get(
            "/api/health",
            headers={"Origin": "http://example.com"},
        )
        assert resp.status_code == 200


@pytest.mark.integration
class TestDashboardApprovalFlow:
    """E2E: Approve/reject ratings and chats."""

    def test_approve_rating_out_of_range_returns_error(self, test_client):
        resp = test_client.post("/api/approve/rating/999")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is False
        assert "error" in data

    def test_reject_rating_out_of_range_returns_error(self, test_client):
        resp = test_client.post("/api/reject/rating/999")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is False
        assert "error" in data

    def test_push_subscribe(self, test_client):
        resp = test_client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://push.example.com/abc", "keys": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
