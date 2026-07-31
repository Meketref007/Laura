"""
Phase 7: Intelligent Support.

Provides lightweight customer support triage, customer memory, escalation
recommendations, and a persistent support history for review.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SUPPORT_INTENT_RESPONSES: dict[str, str] = {
    "tracking": (
        "Seu pedido já foi processado. Consulte o rastreamento em Meus Pedidos e, se precisar,"
        " posso te orientar com o prazo estimado."
    ),
    "delivery": (
        "Posso ajudar com o prazo de entrega. Se quiser, me diga seu pedido para eu conferir o status."
    ),
    "cancelation": (
        "Se o pedido ainda não foi enviado, o cancelamento pode ser solicitado em Meus Pedidos."
    ),
    "refund": (
        "Se houver problema com o produto, posso orientar o passo a passo de devolução ou reembolso."
    ),
    "product": (
        "Para dúvidas sobre o produto, confira a descrição do anúncio e me diga qual ponto você quer confirmar."
    ),
    "complaint": (
        "Sinto muito pela experiência. Vou registrar o caso para análise e priorização.") ,
    "praise": (
        "Obrigado pelo feedback positivo. Fico à disposição para qualquer outra dúvida.") ,
    "other": (
        "Obrigado pela mensagem. Vou analisar sua solicitação e retorno assim que possível."
    ),
}


SUPPORT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tracking": ("rastre", "tracking", "onde está", "onde esta", "entrega", "chegou", "codigo de rastreio"),
    "delivery": ("prazo", "demora", "quando chega", "tempo de entrega", "atraso", "entregue"),
    "cancelation": ("cancelar", "cancelamento", "cancel", "parar pedido"),
    "refund": ("reembolso", "devolução", "devolucao", "troca", "refund", "chargeback"),
    "product": ("tamanho", "cor", "material", "voltagem", "garantia", "compatível", "compativel"),
    "complaint": ("problema", "defeito", "ruim", "errado", "insuport", "péssimo", "pessimo", "reclama", "não gostei", "nao gostei"),
    "praise": ("obrigado", "gostei", "ótimo", "otimo", "excelente", "perfeito"),
}


NEGATIVE_WORDS = (
    "problema",
    "defeito",
    "ruim",
    "péssimo",
    "pessimo",
    "reembolso",
    "devolução",
    "devolucao",
    "cancelar",
    "atraso",
    "reclama",
    "não gostei",
    "nao gostei",
)


@dataclass
class SupportTicket:
    ticket_id: str
    buyer_id: str
    order_id: str | None
    message: str
    intent: str
    priority: str
    escalate: bool
    response_text: str
    created_at: str
    status: str = "open"
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CustomerSupportProfile:
    buyer_id: str
    interaction_count: int = 0
    open_tickets: int = 0
    resolved_tickets: int = 0
    escalation_count: int = 0
    last_intent: str = "other"
    last_contact_at: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupportSummary:
    total_tickets: int
    open_tickets: int
    escalated_tickets: int
    unresolved_buyers: int
    intent_counts: dict[str, int]
    top_buyers: list[dict[str, Any]]
    recent_escalations: list[dict[str, Any]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SupportCenter:
    """Triage, memory, and escalation for customer support."""

    def __init__(self, reports_dir: str | Path = "reports", escalation_open_threshold: int = 2):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.reports_dir / "support_tickets.jsonl"
        self.profile_path = self.reports_dir / "support_customers.json"
        self.escalation_open_threshold = escalation_open_threshold
        self._profiles = self._load_profiles()

    def triage_message(self, buyer_id: str, message: str, order_id: str | None = None) -> SupportTicket:
        cleaned = (message or "").strip()
        intent = self._classify_intent(cleaned)
        priority = self._priority_for_intent(intent, cleaned)
        response_text = SUPPORT_INTENT_RESPONSES.get(intent, SUPPORT_INTENT_RESPONSES["other"])
        escalate = self._should_escalate(intent, priority, buyer_id, cleaned)

        ticket = SupportTicket(
            ticket_id=f"ticket_{uuid.uuid4().hex[:10]}",
            buyer_id=buyer_id,
            order_id=order_id,
            message=cleaned,
            intent=intent,
            priority=priority,
            escalate=escalate,
            response_text=response_text,
            created_at=datetime.now(UTC).isoformat(),
            tags=self._derive_tags(intent, cleaned),
        )

        self._append_history(ticket)
        self._update_profile(ticket)
        return ticket

    def record_resolution(self, ticket_id: str, buyer_id: str, note: str = "") -> bool:
        if not self.history_path.exists():
            return False

        entries: list[dict[str, Any]] = []
        changed = False
        for raw_line in self.history_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except Exception:
                continue
            if isinstance(entry, dict) and entry.get("ticket_id") == ticket_id:
                entry["status"] = "resolved"
                if note:
                    entry.setdefault("notes", []).append(note)
                changed = True
            entries.append(entry)

        if not changed:
            return False

        self.history_path.write_text(
            "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries if isinstance(entry, dict)) + "\n",
            encoding="utf-8",
        )

        profile = self._profiles.get(buyer_id)
        if profile:
            profile.resolved_tickets += 1
            profile.open_tickets = max(0, profile.open_tickets - 1)
            profile.last_contact_at = datetime.now(UTC).isoformat()
            self._profiles[buyer_id] = profile
            self._save_profiles()
        return True

    def load_profile(self, buyer_id: str) -> CustomerSupportProfile:
        return self._profiles.get(buyer_id, CustomerSupportProfile(buyer_id=buyer_id))

    def summary(self, days: int = 30) -> SupportSummary:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        entries = [entry for entry in self._load_history() if self._is_recent(entry, cutoff)]

        intent_counts: dict[str, int] = {}
        open_tickets = 0
        escalated_tickets = 0
        buyers: dict[str, int] = {}
        recent_escalations: list[dict[str, Any]] = []

        for entry in entries:
            intent = str(entry.get("intent", "other"))
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            buyer_id = str(entry.get("buyer_id", "?"))
            buyers[buyer_id] = buyers.get(buyer_id, 0) + 1
            if entry.get("status", "open") != "resolved":
                open_tickets += 1
            if bool(entry.get("escalate")):
                escalated_tickets += 1
                if len(recent_escalations) < 5:
                    recent_escalations.append(
                        {
                            "ticket_id": entry.get("ticket_id"),
                            "buyer_id": buyer_id,
                            "intent": intent,
                            "priority": entry.get("priority"),
                            "created_at": entry.get("created_at"),
                        }
                    )

        top_buyers = [
            {"buyer_id": buyer_id, "tickets": count, **self.load_profile(buyer_id).to_dict()}
            for buyer_id, count in sorted(buyers.items(), key=lambda item: item[1], reverse=True)[:5]
        ]

        recommendations: list[str] = []
        if escalated_tickets:
            recommendations.append("Revisar os tickets escalados com prioridade humana.")
        if intent_counts.get("tracking", 0) + intent_counts.get("delivery", 0) > 0:
            recommendations.append("Manter respostas rápidas para rastreamento e prazo.")
        if intent_counts.get("complaint", 0) > 0 or intent_counts.get("refund", 0) > 0:
            recommendations.append("Priorizar casos de reclamação e reembolso para reduzir atrito.")
        if not recommendations:
            recommendations.append("Fila de suporte está saudável; continuar monitorando.")

        return SupportSummary(
            total_tickets=len(entries),
            open_tickets=open_tickets,
            escalated_tickets=escalated_tickets,
            unresolved_buyers=len([buyer_id for buyer_id, count in buyers.items() if count > 0]),
            intent_counts=intent_counts,
            top_buyers=top_buyers,
            recent_escalations=recent_escalations,
            recommendations=recommendations,
        )

    def _classify_intent(self, message: str) -> str:
        message_lower = message.lower()
        for intent, keywords in SUPPORT_KEYWORDS.items():
            if any(keyword in message_lower for keyword in keywords):
                return intent
        return "other"

    def _priority_for_intent(self, intent: str, message: str) -> str:
        if intent in {"complaint", "refund", "cancelation"}:
            return "high"
        if intent in {"tracking", "delivery", "product"}:
            return "medium"
        if any(word in message.lower() for word in NEGATIVE_WORDS):
            return "high"
        return "low"

    def _should_escalate(self, intent: str, priority: str, buyer_id: str, message: str) -> bool:
        if priority == "high":
            return True
        profile = self.load_profile(buyer_id)
        if profile.open_tickets >= self.escalation_open_threshold:
            return True
        return intent == "other" and any(word in message.lower() for word in NEGATIVE_WORDS)

    def _derive_tags(self, intent: str, message: str) -> list[str]:
        tags = [intent]
        if any(word in message.lower() for word in NEGATIVE_WORDS):
            tags.append("negative_sentiment")
        if "pedido" in message.lower():
            tags.append("order_related")
        return sorted(set(tags))

    def _append_history(self, ticket: SupportTicket) -> None:
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ticket.to_dict(), ensure_ascii=False) + "\n")

    def _load_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for raw_line in self.history_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except Exception:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _is_recent(self, entry: dict[str, Any], cutoff: datetime) -> bool:
        try:
            ts = datetime.fromisoformat(str(entry.get("created_at", "")).replace("Z", "+00:00"))
        except Exception:
            return False
        return ts >= cutoff

    def _load_profiles(self) -> dict[str, CustomerSupportProfile]:
        if not self.profile_path.exists():
            return {}

        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, dict):
            return {}

        profiles: dict[str, CustomerSupportProfile] = {}
        for buyer_id, data in payload.items():
            if not isinstance(data, dict):
                continue
            profiles[str(buyer_id)] = CustomerSupportProfile(
                buyer_id=str(buyer_id),
                interaction_count=int(data.get("interaction_count", 0) or 0),
                open_tickets=int(data.get("open_tickets", 0) or 0),
                resolved_tickets=int(data.get("resolved_tickets", 0) or 0),
                escalation_count=int(data.get("escalation_count", 0) or 0),
                last_intent=str(data.get("last_intent", "other") or "other"),
                last_contact_at=data.get("last_contact_at"),
                tags=[str(tag) for tag in data.get("tags", []) if str(tag).strip()],
            )
        return profiles

    def _save_profiles(self) -> None:
        payload = {buyer_id: profile.to_dict() for buyer_id, profile in self._profiles.items()}
        self.profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _update_profile(self, ticket: SupportTicket) -> None:
        profile = self._profiles.get(ticket.buyer_id) or CustomerSupportProfile(buyer_id=ticket.buyer_id)
        profile.interaction_count += 1
        profile.open_tickets += 1
        if ticket.status == "resolved":
            profile.resolved_tickets += 1
        if ticket.escalate:
            profile.escalation_count += 1
        profile.last_intent = ticket.intent
        profile.last_contact_at = ticket.created_at
        profile.tags = sorted(set(profile.tags).union(ticket.tags))
        self._profiles[ticket.buyer_id] = profile
        self._save_profiles()


def dump_support_summary(summary: SupportSummary, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
