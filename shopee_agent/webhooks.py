"""
Webhook helpers para diferentes plataformas (Slack, Discord, generic HTTP).
"""

from dataclasses import dataclass
from typing import Any

from .alerts import Alert, AlertSeverity


@dataclass
class WebhookPayload:
    """Base webhook payload."""
    text: str = ""
    source: str = "laura"
    severity: str = "info"
    metadata: dict[str, Any] | None = None


class SlackWebhook:
    """Formata alertas para Slack."""

    @staticmethod
    def format(alert: Alert) -> dict[str, Any]:
        """Converte alerta para formato Slack."""
        # Mapear severidade para cor
        color_map = {
            AlertSeverity.CRITICAL: "#FF0000",  # Red
            AlertSeverity.WARNING: "#FFA500",   # Orange
            AlertSeverity.INFO: "#0099FF",      # Blue
        }

        return {
            "attachments": [
                {
                    "color": color_map.get(alert.severity, "#808080"),
                    "title": alert.title,
                    "text": alert.message,
                    "fields": [
                        {
                            "title": "Severity",
                            "value": alert.severity.value,
                            "short": True,
                        },
                        {
                            "title": "Rule",
                            "value": alert.rule.value,
                            "short": True,
                        },
                        {
                            "title": "Timestamp",
                            "value": alert.timestamp,
                            "short": False,
                        },
                    ] + (
                        [
                            {
                                "title": "Action Taken",
                                "value": alert.action_taken,
                                "short": False,
                            }
                        ]
                        if alert.action_taken
                        else []
                    ),
                    "footer": "Laura Store Management",
                    "ts": int(
                        __import__("datetime").datetime.fromisoformat(
                            alert.timestamp
                        ).timestamp()
                    ),
                }
            ]
        }


class DiscordWebhook:
    """Formata alertas para Discord."""

    @staticmethod
    def format(alert: Alert) -> dict[str, Any]:
        """Converte alerta para formato Discord."""
        # Mapear severidade para cor
        color_map = {
            AlertSeverity.CRITICAL: 16711680,  # Red (0xFF0000)
            AlertSeverity.WARNING: 16776960,   # Orange (0xFFFF00)
            AlertSeverity.INFO: 255,            # Blue (0x0000FF)
        }

        description_parts = [alert.message]

        if alert.metrics:
            description_parts.append("\n**Metrics:**")
            for key, value in alert.metrics.items():
                description_parts.append(f"- {key}: {value}")

        if alert.action_taken:
            description_parts.append(f"\n**Action:** {alert.action_taken}")

        return {
            "embeds": [
                {
                    "title": alert.title,
                    "description": "\n".join(description_parts),
                    "color": color_map.get(alert.severity, 8355711),
                    "fields": [
                        {
                            "name": "Severity",
                            "value": alert.severity.value,
                            "inline": True,
                        },
                        {
                            "name": "Rule",
                            "value": alert.rule.value,
                            "inline": True,
                        },
                        {
                            "name": "Timestamp",
                            "value": alert.timestamp,
                            "inline": False,
                        },
                    ],
                    "footer": {
                        "text": "Laura Store Management",
                    },
                }
            ]
        }


class GenericWebhook:
    """Formato genérico para webhooks customizados."""

    @staticmethod
    def format(alert: Alert) -> dict[str, Any]:
        """Converte alerta para formato genérico JSON."""
        return {
            "alert": {
                "rule": alert.rule.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "message": alert.message,
                "timestamp": alert.timestamp,
                "metrics": alert.metrics,
                "action_taken": alert.action_taken,
                "action_result": alert.action_result,
                "metadata": alert.metadata,
            }
        }


def get_webhook_formatter(url: str) -> callable:
    """
    Retorna formatter apropriado baseado na URL.
    
    Args:
        url: URL do webhook
    
    Returns:
        Função que formata alert para o webhook
    """
    if "slack.com" in url:
        return SlackWebhook.format
    elif "discord.com" in url or "discordapp.com" in url:
        return DiscordWebhook.format
    else:
        return GenericWebhook.format
