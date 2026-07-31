"""
Alert system para Laura - Dispara alertas baseado em condições de saúde da loja.

Features:
- Rules engine (margin < 5%, ROAS < 1, etc)
- Webhook integration (Slack, Discord, generic HTTP)
- Alert history & audit logging
- Threshold-based triggering with cooldown
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import requests

from .logger import debug, info, warning


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class AlertRule(str, Enum):
    """Predefined alert rules."""
    LOW_MARGIN = "low_margin"  # margin < 5%
    HIGH_REFUND_RATE = "high_refund_rate"  # refund_rate > 5%
    LOW_ROAS = "low_roas"  # roas < 1
    NO_ORDERS = "no_orders"  # orders = 0
    LOW_INVENTORY = "low_inventory"  # products with stock < threshold
    HIGH_AD_SPEND = "high_ad_spend"  # ad_spend > revenue * threshold
    OLLAMA_OFFLINE = "ollama_offline"  # LLM unavailable
    API_ERROR = "api_error"  # Shopee API errors


@dataclass
class Alert:
    """Single alert instance."""
    rule: AlertRule
    severity: AlertSeverity
    title: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metrics: dict[str, Any] = field(default_factory=dict)
    action_taken: str | None = None
    action_result: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertConfig:
    """Configuration for alert rules."""
    rule: AlertRule
    enabled: bool = True
    severity: AlertSeverity = AlertSeverity.WARNING
    threshold: float = 0.0
    cooldown_minutes: int = 60  # Don't repeat alert more than once per hour
    webhook_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AlertsEngine:
    """
    Engine que avalia condições e dispara alertas.
    
    Features:
    - Rule-based alert triggering
    - Cooldown to prevent alert spam
    - Webhook integration
    - History tracking
    """

    def __init__(
        self,
        history_dir: str = "reports",
        webhook_timeout_seconds: int = 5,
    ):
        """
        Inicializa engine de alertas.
        
        Args:
            history_dir: Diretório para armazenar histórico
            webhook_timeout_seconds: Timeout para chamadas webhook
        """
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.webhook_timeout = webhook_timeout_seconds
        self.history_file = self.history_dir / "laura_alerts_history.jsonl"
        self.cooldowns: dict[AlertRule, datetime] = {}

        info("AlertsEngine initialized", history_dir=str(self.history_dir))

    def evaluate(
        self,
        metrics: dict[str, Any],
        rules_config: dict[AlertRule, AlertConfig],
    ) -> list[Alert]:
        """
        Avalia métricas contra regras e retorna alertas.
        
        Args:
            metrics: Dicionário com métricas da loja
            rules_config: Configuração de regras
        
        Returns:
            Lista de alertas disparados
        """
        alerts: list[Alert] = []

        for rule, config in rules_config.items():
            if not config.enabled:
                continue

            # Check cooldown
            if not self._check_cooldown(rule, config.cooldown_minutes):
                debug(f"Rule {rule} still in cooldown", rule=rule)
                continue

            # Evaluate rule
            alert = self._eval_rule(rule, metrics, config)
            if alert:
                alerts.append(alert)
                self._set_cooldown(rule)

        return alerts

    def _eval_rule(
        self,
        rule: AlertRule,
        metrics: dict[str, Any],
        config: AlertConfig,
    ) -> Alert | None:
        """Avalia uma regra específica."""

        if rule == AlertRule.LOW_MARGIN:
            margin = metrics.get("margin_pct", 0)
            if margin < config.threshold:
                return Alert(
                    rule=rule,
                    severity=config.severity,
                    title="Margem de lucro crítica",
                    message=f"Margem caiu para {margin:.1f}% (limite: {config.threshold}%)",
                    metrics={"margin_pct": margin},
                    metadata={"threshold": config.threshold},
                )

        elif rule == AlertRule.HIGH_REFUND_RATE:
            refund_rate = metrics.get("refund_rate_pct", 0)
            if refund_rate > config.threshold:
                return Alert(
                    rule=rule,
                    severity=config.severity,
                    title="Taxa de reembolso elevada",
                    message=f"Reembolsos em {refund_rate:.1f}% (limite: {config.threshold}%)",
                    metrics={"refund_rate_pct": refund_rate},
                    metadata={"threshold": config.threshold},
                )

        elif rule == AlertRule.LOW_ROAS:
            roas = metrics.get("roas", 0)
            if roas < config.threshold and roas > 0:
                return Alert(
                    rule=rule,
                    severity=config.severity,
                    title="ROAS baixo demais",
                    message=f"ROAS em {roas:.2f}x (limite: {config.threshold}x)",
                    metrics={"roas": roas},
                    metadata={"threshold": config.threshold},
                )

        elif rule == AlertRule.NO_ORDERS:
            orders = metrics.get("order_volume", 0)
            if orders == 0 and metrics.get("orders_count", 0) == 0:
                return Alert(
                    rule=rule,
                    severity=config.severity,
                    title="Nenhum pedido no período",
                    message="Nenhuma atividade de vendas detectada",
                    metrics={"order_volume": 0},
                )

        elif rule == AlertRule.OLLAMA_OFFLINE:
            if metrics.get("ollama_error") or "fallback" in str(metrics.get("model", "")):
                return Alert(
                    rule=rule,
                    severity=config.severity,
                    title="LLM Ollama offline",
                    message="Sistema de análise caiu para fallback heurístico",
                    metrics={"model": metrics.get("model")},
                )

        elif rule == AlertRule.API_ERROR:
            if metrics.get("api_errors", 0) > 0:
                return Alert(
                    rule=rule,
                    severity=config.severity,
                    title="Erro na API Shopee",
                    message=f"Detectados {metrics.get('api_errors', 0)} erros de API",
                    metrics={"api_errors": metrics.get("api_errors", 0)},
                )

        return None

    def dispatch(
        self,
        alerts: list[Alert],
        webhooks: dict[AlertSeverity, list[str]],
    ) -> dict[str, Any]:
        """
        Dispara alertas para webhooks.
        
        Args:
            alerts: Lista de alertas
            webhooks: Mapa de severity → URLs de webhook
        
        Returns:
            Dicionário com resultados do envio
        """
        results = {
            "sent": 0,
            "failed": 0,
            "errors": [],
            "details": [],
        }

        for alert in alerts:
            # Log to history first
            self._log_alert(alert)

            # Notify via Telegram if bot is running
            try:
                from .telegram_narrator import narrador
                narrador.critico(f"Alerta: {alert.title} — {alert.message}")
            except Exception:
                pass

            # Send email if SMTP is configured
            try:
                import os as _os
                if _os.getenv("SMTP_HOST"):
                    from .reporting import ReportingEngine
                    engine = ReportingEngine()
                    engine.send_email(
                        {"summary": f"{alert.title}: {alert.message}"},
                        recipients=[_os.getenv("ALERT_EMAIL", "")],
                        format="html",
                    )
            except Exception:
                pass

            # Get webhook URLs for this severity
            urls = webhooks.get(alert.severity, [])
            if not urls:
                debug(f"No webhooks configured for {alert.severity}")
                continue

            # Send to each webhook
            for url in urls:
                try:
                    self._send_webhook(url, alert)
                    results["sent"] += 1
                    results["details"].append({
                        "rule": alert.rule.value,
                        "url": url,
                        "status": "sent",
                    })
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append(str(e))
                    results["details"].append({
                        "rule": alert.rule.value,
                        "url": url,
                        "status": "failed",
                        "error": str(e),
                    })

        return results

    def _send_webhook(self, url: str, alert: Alert) -> None:
        """Envia alerta para webhook."""
        payload = {
            "rule": alert.rule.value,
            "severity": alert.severity.value,
            "title": alert.title,
            "message": alert.message,
            "timestamp": alert.timestamp,
            "metrics": alert.metrics,
            "action_taken": alert.action_taken,
            "metadata": alert.metadata,
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.webhook_timeout,
            )
            response.raise_for_status()
            debug("Webhook sent successfully", url=url, rule=alert.rule)
        except Exception as e:
            warning("Webhook failed", url=url, rule=alert.rule, error=str(e)[:100])
            raise

    def _log_alert(self, alert: Alert) -> None:
        """Registra alerta no histórico."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(alert), ensure_ascii=False) + "\n")

    def get_history(self, limit: int = 100) -> list[dict]:
        """Retorna histórico de alertas recentes."""
        if not self.history_file.exists():
            return []

        alerts = []
        with open(self.history_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        alerts.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return alerts[-limit:]

    def _check_cooldown(self, rule: AlertRule, cooldown_minutes: int) -> bool:
        """Verifica se regra está em cooldown."""
        if rule not in self.cooldowns:
            return True

        elapsed = datetime.now(UTC) - self.cooldowns[rule]
        return elapsed >= timedelta(minutes=cooldown_minutes)

    def _set_cooldown(self, rule: AlertRule) -> None:
        """Define cooldown para regra."""
        self.cooldowns[rule] = datetime.now(UTC)


def get_default_alert_config() -> dict[AlertRule, AlertConfig]:
    """Retorna configuração padrão de alertas."""
    return {
        AlertRule.LOW_MARGIN: AlertConfig(
            rule=AlertRule.LOW_MARGIN,
            enabled=True,
            severity=AlertSeverity.CRITICAL,
            threshold=5.0,  # % margin
            cooldown_minutes=60,
        ),
        AlertRule.HIGH_REFUND_RATE: AlertConfig(
            rule=AlertRule.HIGH_REFUND_RATE,
            enabled=True,
            severity=AlertSeverity.CRITICAL,
            threshold=5.0,  # % refunds
            cooldown_minutes=60,
        ),
        AlertRule.LOW_ROAS: AlertConfig(
            rule=AlertRule.LOW_ROAS,
            enabled=True,
            severity=AlertSeverity.CRITICAL,
            threshold=1.0,  # ROAS multiplier
            cooldown_minutes=120,
        ),
        AlertRule.NO_ORDERS: AlertConfig(
            rule=AlertRule.NO_ORDERS,
            enabled=True,
            severity=AlertSeverity.WARNING,
            threshold=0.0,
            cooldown_minutes=1440,  # 24 hours
        ),
        AlertRule.OLLAMA_OFFLINE: AlertConfig(
            rule=AlertRule.OLLAMA_OFFLINE,
            enabled=True,
            severity=AlertSeverity.WARNING,
            cooldown_minutes=30,
        ),
        AlertRule.API_ERROR: AlertConfig(
            rule=AlertRule.API_ERROR,
            enabled=True,
            severity=AlertSeverity.INFO,
            threshold=1.0,
            cooldown_minutes=15,
        ),
    }


def create_alerts_engine() -> AlertsEngine:
    """Factory para criar engine de alertas."""
    return AlertsEngine()
