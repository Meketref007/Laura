from unittest.mock import Mock

from shopee_agent.insights_llm import InsightsAnalyzer


def test_analyze_trend_insufficient_data():
    ia = InsightsAnalyzer()
    res = ia.analyze_trend_with_ai("nonexistent_metric", days=1)
    assert res["status"] == "insufficient_data"


def test_generate_smart_recommendations_with_mocked_llm():
    ia = InsightsAnalyzer()
    ia.analyzer = Mock()
    ia._ensure_analyzer = Mock(return_value=True)
    ia.analyzer.analyze.return_value = {"reasoning": "Recomendação mock"}
    res = ia.generate_smart_recommendations(context="general", language="pt_BR")
    assert "Recomendação mock" in res["ai_recommendations"]


def test_explain_anomaly_with_mocked_llm():
    ia = InsightsAnalyzer()
    ia.analyzer = Mock()
    ia._ensure_analyzer = Mock(return_value=True)
    ia.analyzer.analyze.return_value = {"reasoning": "Explicação mock"}
    anomaly = {"type": "refund_spike", "severity": "HIGH", "timestamp": "2026-05-01T00:00:00Z", "value": 123}
    res = ia.explain_anomaly_with_ai(anomaly, language="pt_BR")
    assert "Explicação mock" in res["ai_explanation"]
