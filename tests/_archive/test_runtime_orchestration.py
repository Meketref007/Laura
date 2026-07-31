from __future__ import annotations

from shopee_agent.runtime import LauraRuntime


class TestLauraRuntimeOrchestration:
    def test_run_cycle_executes_registered_components_in_order(self):
        runtime = LauraRuntime(name="test-runtime")
        calls: list[str] = []

        def decision_cycle() -> dict[str, object]:
            calls.append("decision")
            return {"ok": True}

        def autonomous_cycle() -> dict[str, object]:
            calls.append("autonomous")
            return {"ok": True}

        runtime.register_component("decision_cycle", decision_cycle, kind="decision")
        runtime.register_component("autonomous_cycle", autonomous_cycle, kind="automation")

        result = runtime.run_cycle()

        assert calls == ["decision", "autonomous"]
        assert result["components"]["decision_cycle"]["ok"] is True
        assert result["components"]["autonomous_cycle"]["ok"] is True
        assert result["errors"] == []
        assert runtime.services["decision_cycle"].last_error is None
        assert runtime.services["autonomous_cycle"].status == "healthy"

    def test_run_cycle_honors_component_dependencies(self):
        runtime = LauraRuntime(name="test-runtime")
        calls: list[str] = []

        def decision_cycle() -> dict[str, object]:
            calls.append("decision")
            return {"ok": True}

        def autonomous_cycle() -> dict[str, object]:
            calls.append("autonomous")
            return {"ok": True}

        runtime.register_component("autonomous_cycle", autonomous_cycle, kind="automation", depends_on=["decision_cycle"])
        runtime.register_component("decision_cycle", decision_cycle, kind="decision")

        result = runtime.run_cycle()

        assert calls == ["decision", "autonomous"]
        assert result["components"]["decision_cycle"]["ok"] is True
        assert result["components"]["autonomous_cycle"]["ok"] is True
        assert runtime.status_snapshot()["orchestrated_components"] == ["decision_cycle", "autonomous_cycle"]
        assert runtime.status_snapshot()["component_groups"]["decision"] == ["decision_cycle"]

    def test_run_cycle_records_failed_component(self):
        runtime = LauraRuntime(name="test-runtime")

        def good_component() -> dict[str, object]:
            return {"ok": True}

        def bad_component() -> dict[str, object]:
            raise RuntimeError("boom")

        runtime.register_component("good_component", good_component)
        runtime.register_component("bad_component", bad_component)

        result = runtime.run_cycle()

        assert result["components"]["good_component"]["ok"] is True
        assert result["errors"][0]["component"] == "bad_component"
        assert runtime.services["bad_component"].status == "error"
        assert runtime.services["bad_component"].last_error == "boom"
        assert runtime.health_snapshot()["status"] == "critical"
