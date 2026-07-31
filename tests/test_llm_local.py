from __future__ import annotations

from shopee_agent.llm_local import LauraOllamaAnalyzer


def test_fail_fast_if_model_not_available_uses_api_tags_preflight(monkeypatch):
    analyzer = LauraOllamaAnalyzer.__new__(LauraOllamaAnalyzer)
    analyzer.model = "tinyllama"

    calls: list[str] = []

    def fake_available() -> bool:
        calls.append("available")
        return False

    def fake_loaded() -> bool:
        raise AssertionError("_check_model_loaded should not run when /api/tags preflight fails")

    def fake_fallback_dict(**kwargs):
        return {"decision": "fallback", "prompt_type": kwargs["prompt_type"]}

    monkeypatch.setattr(analyzer, "_check_model_available", fake_available)
    monkeypatch.setattr(analyzer, "_check_model_loaded", fake_loaded)
    monkeypatch.setattr(analyzer, "_heuristic_fallback_dict", fake_fallback_dict)

    result = analyzer._fail_fast_if_unloaded(
        fallback_on_error=True,
        metrics={"revenue": 0.0},
        prompt_type="general_agent",
        max_tokens=64,
    )

    assert result == {"decision": "fallback", "prompt_type": "general_agent"}
    assert calls == ["available"]
