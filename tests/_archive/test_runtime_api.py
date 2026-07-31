from __future__ import annotations

from fastapi.testclient import TestClient

from shopee_agent.api_app import create_app
from shopee_agent.runtime import LauraRuntime


class TestLauraRuntime:
    def test_health_snapshot_reflects_registered_services(self):
        runtime = LauraRuntime(name="test-runtime")
        runtime.register_service("webhook", status="healthy")
        runtime.register_service("decision", status="healthy")

        health = runtime.health_snapshot()

        assert health["ok"] is True
        assert health["status"] == "healthy"
        assert health["service_count"] == 2

    def test_unhealthy_service_marks_runtime_critical(self):
        runtime = LauraRuntime(name="test-runtime")
        runtime.register_service("api", status="healthy")
        runtime.register_service("worker", status="error")

        health = runtime.health_snapshot()

        assert health["ok"] is False
        assert health["status"] == "critical"
        assert "worker" in health["unhealthy_services"]


class TestLauraApiApp:
    def test_api_exposes_health_status_and_cycle(self):
        runtime = LauraRuntime(name="test-runtime")

        def fake_cycle() -> dict[str, object]:
            return {"timestamp": "2026-05-14T12:00:00+00:00", "components": {"decision_cycle": {"ok": True}}}

        runtime.run_cycle = fake_cycle  # type: ignore[method-assign]
        runtime.register_service("runtime", status="healthy")

        client = TestClient(create_app(runtime))

        health_response = client.get("/api/v1/health")
        status_response = client.get("/api/v1/runtime/status")
        cycle_response = client.post("/api/v1/runtime/cycle")

        assert health_response.status_code == 200
        assert health_response.json()["ok"] is True

        assert status_response.status_code == 200
        assert status_response.json()["name"] == "test-runtime"

        assert cycle_response.status_code == 200
        assert cycle_response.json()["components"]["decision_cycle"]["ok"] is True
