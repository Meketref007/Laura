"""
PHASE 20: AI-Powered Insights & LLM Analysis
Provides intelligent insights, trend analysis, and anomaly explanations using local LLM
"""

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .llm_local import LauraOllamaAnalyzer, check_ollama_running
from .llm_providers import LLMEngine


class InsightsAnalyzer:
    """AI-powered insights generator using local LLM"""

    def __init__(self, reports_dir: str = "reports", llm_model: str = "llama3.2:3b", llm_timeout_seconds: int = 15, llm_engine: LLMEngine | None = None):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)
        self.llm_model = llm_model
        self.llm_timeout_seconds = llm_timeout_seconds
        self.analyzer: LauraOllamaAnalyzer | None = None
        self._llm_engine = llm_engine or LLMEngine()

    def _ensure_analyzer(self) -> bool:
        """Ensure the local LLM analyzer is available without blocking startup.

        Returns True if analyzer is ready, False otherwise.
        """
        if self.analyzer is not None:
            return True

        # Avoid attempting to start Ollama automatically here to prevent long blocking.
        try:
            if not check_ollama_running():
                return False
            # Do not trigger synchronous model pull here to avoid long blocking.
            self.analyzer = LauraOllamaAnalyzer(model=self.llm_model, pull_model=False)
            self.analyzer.request_timeout_seconds = self.llm_timeout_seconds
            return True
        except Exception:
            self.analyzer = None
            return False

    def _safe_analyze(self, payload: dict, prompt_type: str = "general_agent", max_tokens: int = 256) -> dict:
        """Call the analyzer safely with fallback.

        Returns a dict with at least a `reasoning` key.
        """
        # If analyzer is already set (e.g. by tests), use it directly
        if self.analyzer is not None:
            try:
                result = self.analyzer.analyze(payload, prompt_type=prompt_type, max_tokens=max_tokens)
                if isinstance(result, dict):
                    return result
                try:
                    return dict(result)
                except Exception:
                    return {"reasoning": str(result)}
            except Exception as e:
                return {"reasoning": f"AI analysis failed: {e}"}

        # Try LLMEngine first
        try:
            result = self._llm_engine.analyze(prompt_type, payload)
            if "_llm" in result:
                return result
        except Exception:
            pass

        # Fall back to LauraOllamaAnalyzer
        if not self._ensure_analyzer():
            return {"reasoning": f"AI unavailable or Ollama not running (prompt_type={prompt_type})"}

        try:
            result = self.analyzer.analyze(payload, prompt_type=prompt_type, max_tokens=max_tokens)
            if isinstance(result, dict):
                return result
            try:
                return dict(result)
            except Exception:
                return {"reasoning": str(result)}
        except Exception as e:
            return {"reasoning": f"AI analysis failed: {e}"}

    def analyze_trend_with_ai(self, metric_name: str, days: int = 30, language: str = "pt_BR") -> dict[str, Any]:
        """Analyze trend using AI explanation"""
        data = self._collect_metric_history(metric_name, days)

        if not data or len(data) < 3:
            return {
                "metric": metric_name,
                "status": "insufficient_data",
                "data_points": len(data)
            }

        values = [d.get('value', 0) for d in data]
        trend = self._calculate_trend(values)
        direction = "increasing" if trend > 0.05 else "decreasing" if trend < -0.05 else "stable"

        # Generate AI prompt for analysis
        prompt = self._build_trend_prompt(
            metric_name, values, direction, language
        )

        # Get LLM analysis
        # Use LLM via analyze method
        result = self._safe_analyze({"prompt": prompt}, prompt_type="general_agent", max_tokens=96)
        ai_explanation = result.get("reasoning", "AI analysis temporarily unavailable")

        return {
            "metric": metric_name,
            "period_days": days,
            "data_points": len(values),
            "trend": {
                "direction": direction,
                "coefficient": round(trend, 3),
                "mean": round(statistics.mean(values), 2),
                "stdev": round(statistics.stdev(values) if len(values) > 1 else 0, 2)
            },
            "ai_analysis": ai_explanation,
            "language": language,
            "confidence": self._estimate_confidence(len(values), statistics.stdev(values) if len(values) > 1 else 0)
        }

    def explain_anomaly_with_ai(self, anomaly_data: dict[str, Any], language: str = "pt_BR") -> dict[str, Any]:
        """Explain anomaly using AI reasoning"""
        prompt = self._build_anomaly_prompt(anomaly_data, language)

        result = self._safe_analyze({"prompt": prompt}, prompt_type="general_agent", max_tokens=96)
        ai_explanation = result.get("reasoning", "AI analysis temporarily unavailable")

        return {
            "anomaly_type": anomaly_data.get("type", "unknown"),
            "severity": anomaly_data.get("severity", "MEDIUM"),
            "timestamp": anomaly_data.get("timestamp", ""),
            "value": anomaly_data.get("value", 0),
            "ai_explanation": ai_explanation,
            "recommended_actions": self._extract_actions_from_explanation(ai_explanation),
            "language": language
        }

    def generate_smart_recommendations(self, context: str = "general", language: str = "pt_BR") -> dict[str, Any]:
        """Generate AI-powered recommendations"""
        # Collect current metrics
        health = self._read_json("laura_health_latest.json") or {}
        alerts_count = self._count_recent("laura_alerts_history.jsonl")
        refunds_count = self._count_recent("laura_refunds_history.jsonl")

        prompt = self._build_recommendations_prompt(
            context,
            {
                "health_score": health.get("health_score", 50),
                "alerts": alerts_count,
                "refunds": refunds_count,
            },
            language
        )

        result = self._safe_analyze({"prompt": prompt}, prompt_type="general_agent", max_tokens=96)
        recommendations = result.get("reasoning", "AI recommendations temporarily unavailable")

        return {
            "context": context,
            "generated_at": datetime.now().isoformat(),
            "ai_recommendations": recommendations,
            "priority_actions": self._extract_priority_actions(recommendations),
            "language": language,
            "confidence": 0.85
        }

    def generate_executive_summary(self, days: int = 7, language: str = "pt_BR") -> dict[str, Any]:
        """Generate AI-powered executive summary"""
        # Collect all metrics
        metrics_data = {
            "period": f"last_{days}_days",
            "alerts": self._count_recent("laura_alerts_history.jsonl"),
            "refunds": self._count_recent("laura_refunds_history.jsonl"),
            "health_score": self._read_json("laura_health_latest.json", {}).get("health_score", 50),
            "timestamp": datetime.now().isoformat()
        }

        prompt = self._build_summary_prompt(metrics_data, language)

        result = self._safe_analyze({"prompt": prompt}, prompt_type="general_agent", max_tokens=96)
        summary = result.get("reasoning", "AI summary temporarily unavailable")

        return {
            "summary_period_days": days,
            "generated_at": datetime.now().isoformat(),
            "executive_summary": summary,
            "key_metrics": metrics_data,
            "language": language,
            "readiness_score": self._calculate_readiness(metrics_data)
        }

    def predict_next_actions(self, failure_mode: str = "refund_spike", language: str = "pt_BR") -> dict[str, Any]:
        """Predict what could go wrong and recommend preventive actions"""
        prompt = self._build_prediction_prompt(failure_mode, language)

        result = self._safe_analyze({"prompt": prompt}, prompt_type="general_agent", max_tokens=256)
        prediction = result.get("reasoning", "AI prediction temporarily unavailable")

        return {
            "failure_mode": failure_mode,
            "predicted_at": datetime.now().isoformat(),
            "ai_prediction": prediction,
            "prevention_steps": self._extract_prevention_steps(prediction),
            "mitigation_checklist": self._build_mitigation_checklist(failure_mode),
            "language": language
        }

    def batch_analyze_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Analyze recent alerts batch with AI"""
        alerts = self._read_jsonl("laura_alerts_history.jsonl")
        recent_alerts = alerts[-limit:] if alerts else []

        analyzed = []
        for alert in recent_alerts:
            result = self._safe_analyze({"prompt": f"Contexto para alerta {alert.get('type')}: {alert.get('message', '')}"}, prompt_type="general_agent", max_tokens=160)
            analysis = {
                "alert_type": alert.get("type", "unknown"),
                "severity": alert.get("severity", "MEDIUM"),
                "timestamp": alert.get("timestamp", ""),
                "value": alert.get("value", 0),
                "ai_context": result.get("reasoning", "AI analysis unavailable")
            }
            analyzed.append(analysis)

        return analyzed

    # Helper methods

    def _build_trend_prompt(self, metric_name: str, values: list[float], direction: str, language: str) -> str:
        """Build prompt for trend analysis"""
        if language == "pt_BR":
            return f"""Analize a tendência métrica '{metric_name}' nos últimos dados:
Valores: {values[-7:]}
Direção: {direction}
Média: {statistics.mean(values):.2f}
Desvio padrão: {statistics.stdev(values) if len(values) > 1 else 0:.2f}

Por favor, explique:
1. Por que esta métrica está {direction}?
2. Qual é o impacto no negócio?
3. Que ações recomendar?"""
        else:
            return f"""Analyze metric '{metric_name}' trend in recent data:
Values: {values[-7:]}
Direction: {direction}
Mean: {statistics.mean(values):.2f}
Std Dev: {statistics.stdev(values) if len(values) > 1 else 0:.2f}

Please explain:
1. Why is this metric {direction}?
2. What's the business impact?
3. What actions to recommend?"""

    def _build_anomaly_prompt(self, anomaly: dict[str, Any], language: str) -> str:
        """Build prompt for anomaly explanation"""
        if language == "pt_BR":
            return f"""Explique esta anomalia detectada:
Tipo: {anomaly.get('type', 'unknown')}
Severidade: {anomaly.get('severity', 'MEDIUM')}
Valor: {anomaly.get('value', 0)}
Limiar: {anomaly.get('threshold', 'N/A')}
Timestamp: {anomaly.get('timestamp', '')}

Por favor:
1. Por que isso é uma anomalia?
2. Quais são os riscos?
3. Que ações tomar imediatamente?"""
        else:
            return f"""Explain this detected anomaly:
Type: {anomaly.get('type', 'unknown')}
Severity: {anomaly.get('severity', 'MEDIUM')}
Value: {anomaly.get('value', 0)}
Threshold: {anomaly.get('threshold', 'N/A')}
Timestamp: {anomaly.get('timestamp', '')}

Please:
1. Why is this an anomaly?
2. What are the risks?
3. What immediate actions to take?"""

    def _build_recommendations_prompt(self, context: str, metrics: dict[str, Any], language: str) -> str:
        """Build prompt for recommendations"""
        if language == "pt_BR":
            return f"""Baseado neste contexto de loja, recomende ações:
Contexto: {context}
Saúde da Loja: {metrics.get('health_score', 50)}%
Alertas Recentes: {metrics.get('alerts', 0)}
Devoluções Recentes: {metrics.get('refunds', 0)}

Por favor forneça:
1. 3-5 recomendações acionáveis
2. Prioridade de cada ação
3. Impacto esperado"""
        else:
            return f"""Based on this store context, recommend actions:
Context: {context}
Store Health: {metrics.get('health_score', 50)}%
Recent Alerts: {metrics.get('alerts', 0)}
Recent Refunds: {metrics.get('refunds', 0)}

Please provide:
1. 3-5 actionable recommendations
2. Priority of each action
3. Expected impact"""

    def _build_summary_prompt(self, metrics: dict[str, Any], language: str) -> str:
        """Build prompt for executive summary"""
        if language == "pt_BR":
            return f"""Escreva um resumo executivo para a gerência baseado nesses dados:
Período: {metrics.get('period', '7 dias')}
Alertas: {metrics.get('alerts', 0)}
Devoluções: {metrics.get('refunds', 0)}
Saúde: {metrics.get('health_score', 50)}%

Formato:
1. Situação atual (2-3 linhas)
2. Principais desafios (3-4 pontos)
3. Oportunidades (2-3 pontos)
4. Próximos passos (2-3 ações)"""
        else:
            return f"""Write an executive summary for management based on this data:
Period: {metrics.get('period', '7 days')}
Alerts: {metrics.get('alerts', 0)}
Refunds: {metrics.get('refunds', 0)}
Health: {metrics.get('health_score', 50)}%

Format:
1. Current situation (2-3 lines)
2. Main challenges (3-4 points)
3. Opportunities (2-3 points)
4. Next steps (2-3 actions)"""

    def _build_prediction_prompt(self, failure_mode: str, language: str) -> str:
        """Build prompt for failure prediction"""
        if language == "pt_BR":
            return f"""Dado o modo de falha '{failure_mode}', preveja o que pode acontecer:
1. Quais são os indicadores de alerta?
2. Qual é a sequência provável de eventos?
3. Como preparar-se preventivamente?
4. Qual é o plano de resposta?"""
        else:
            return f"""Given the failure mode '{failure_mode}', predict what could happen:
1. What are the warning indicators?
2. What's the likely sequence of events?
3. How to prepare preventively?
4. What's the response plan?"""

    def _calculate_trend(self, values: list[float]) -> float:
        """Calculate trend coefficient"""
        if len(values) < 2:
            return 0

        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(values)

        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        return numerator / denominator if denominator != 0 else 0

    def _estimate_confidence(self, data_points: int, stdev: float) -> float:
        """Estimate confidence in analysis"""
        if data_points < 7:
            return 0.5
        elif data_points < 14:
            return 0.65
        elif data_points < 30:
            return 0.8
        else:
            return 0.9

    def _extract_actions_from_explanation(self, explanation: str) -> list[str]:
        """Extract action items from AI explanation"""
        actions = []
        lines = explanation.split('\n')
        for line in lines:
            if any(prefix in line.lower() for prefix in ['action', 'fazer', 'do', 'recomend', 'consider']):
                clean_line = line.strip('- •*').strip()
                if clean_line and len(clean_line) > 5:
                    actions.append(clean_line)
        return actions[:5]  # Top 5 actions

    def _extract_priority_actions(self, recommendations: str) -> list[dict[str, str]]:
        """Extract priority-ordered actions"""
        actions = []
        lines = recommendations.split('\n')
        for i, line in enumerate(lines[:10]):  # First 10 lines
            if line.strip():
                actions.append({
                    "order": i + 1,
                    "action": line.strip('- •*').strip(),
                    "priority": "HIGH" if i < 3 else "MEDIUM" if i < 6 else "LOW"
                })
        return actions

    def _extract_prevention_steps(self, prediction: str) -> list[str]:
        """Extract prevention steps from prediction"""
        steps = []
        lines = prediction.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['prevent', 'prepar', 'monit', 'impedir', 'preparar']):
                clean = line.strip('- •*').strip()
                if clean and len(clean) > 5:
                    steps.append(clean)
        return steps[:5]

    def _build_mitigation_checklist(self, failure_mode: str) -> list[dict[str, Any]]:
        """Build mitigation checklist for failure mode"""
        checklists = {
            "refund_spike": [
                {"item": "Verificar qualidade dos produtos", "status": "pending"},
                {"item": "Revisar descrições de produtos", "status": "pending"},
                {"item": "Contatar clientes insatisfeitos", "status": "pending"},
                {"item": "Oferecer cupom de desconto", "status": "pending"},
            ],
            "api_error": [
                {"item": "Verificar conectividade", "status": "pending"},
                {"item": "Revisar logs da API", "status": "pending"},
                {"item": "Testar endpoint", "status": "pending"},
                {"item": "Ativar circuit breaker", "status": "pending"},
            ],
            "high_alert_rate": [
                {"item": "Revisar regras de alerta", "status": "pending"},
                {"item": "Identificar falsos positivos", "status": "pending"},
                {"item": "Ajustar thresholds", "status": "pending"},
                {"item": "Investigar causa raiz", "status": "pending"},
            ]
        }
        return checklists.get(failure_mode, [])

    def _collect_metric_history(self, metric_name: str, days: int) -> list[dict[str, Any]]:
        """Collect historical metric data"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        if metric_name == "alerts":
            alerts = self._read_jsonl("laura_alerts_history.jsonl")
            return [{"value": 1, "timestamp": a.get('timestamp', '')} for a in alerts if a.get('timestamp', '') >= cutoff]
        elif metric_name == "refunds":
            refunds = self._read_jsonl("laura_refunds_history.jsonl")
            return [{"value": 1, "timestamp": r.get('timestamp', '')} for r in refunds if r.get('timestamp', '') >= cutoff]
        return []

    def _count_recent(self, filename: str) -> int:
        """Count recent items"""
        filepath = self.reports_dir / filename
        if not filepath.exists():
            return 0
        try:
            lines = filepath.read_text().strip().split('\n')
            return len([_line for _line in lines if _line])
        except Exception:
            return 0

    def _read_json(self, filename: str, default: Any = None) -> dict | None:
        """Read JSON file"""
        filepath = self.reports_dir / filename
        if not filepath.exists():
            return default
        try:
            return json.loads(filepath.read_text())
        except Exception:
            return default

    def _read_jsonl(self, filename: str) -> list[dict]:
        """Read JSONL file"""
        filepath = self.reports_dir / filename
        if not filepath.exists():
            return []
        try:
            lines = filepath.read_text().strip().split('\n')
            return [json.loads(line) for line in lines if line]
        except Exception:
            return []

    def _calculate_readiness(self, metrics: dict[str, Any]) -> float:
        """Calculate overall readiness score"""
        health = metrics.get("health_score", 50) / 100
        alerts_factor = 1.0 - min(metrics.get("alerts", 0) / 50, 1.0)
        refunds_factor = 1.0 - min(metrics.get("refunds", 0) / 20, 1.0)

        return round((health * 0.4 + alerts_factor * 0.35 + refunds_factor * 0.25) * 100, 1)
