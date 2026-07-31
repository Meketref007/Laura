"""
Refund Management System para Laura - Handle devoluções e reembolsos automaticamente.

Features:
- Listar devoluções pendentes/em progresso
- Processar reembolsos com validação
- Auto-remediation para altas taxas de devolução
- Rastreamento de padrões de devolução por produto
- Sugestões inteligentes de ação (reembolso, reposição, etc)
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from .logger import debug, info, warning


class RefundStatus(str, Enum):
    """Status de uma devolução."""
    PENDING = "pending"  # Aguardando revisão
    APPROVED = "approved"  # Reembolso aprovado
    REJECTED = "rejected"  # Devolução rejeitada
    COMPLETED = "completed"  # Reembolso processado
    REFUNDED = "refunded"  # Reembolso finalizado


class RefundReason(str, Enum):
    """Razões comuns de devolução."""
    PRODUCT_DEFECTIVE = "product_defective"
    NOT_AS_DESCRIBED = "not_as_described"
    WRONG_ITEM = "wrong_item"
    DAMAGED_IN_TRANSIT = "damaged_in_transit"
    CHANGED_MIND = "changed_mind"
    BETTER_PRICE_ELSEWHERE = "better_price_elsewhere"
    OTHER = "other"


class RefundDecision(str, Enum):
    """Decisão automática de reembolso."""
    AUTO_APPROVE = "auto_approve"  # Aceitar automaticamente
    AUTO_REJECT = "auto_reject"  # Rejeitar automaticamente
    MANUAL_REVIEW = "manual_review"  # Requer revisão manual
    CONTACT_BUYER = "contact_buyer"  # Entrar em contato


@dataclass
class Refund:
    """Representação de uma devolução."""
    refund_id: str
    order_id: str
    buyer_id: str
    product_id: str
    reason: RefundReason
    status: RefundStatus
    amount: float
    requested_at: str
    resolved_at: str | None = None
    comment: str | None = None
    decision: RefundDecision | None = None
    auto_remediation: bool = False


@dataclass
class RefundStats:
    """Estatísticas de reembolsos."""
    total_refunds: int
    pending_count: int
    approval_rate: float  # % de reembolsos aprovados
    avg_resolution_time_hours: float
    high_refund_products: list[dict[str, Any]]  # Produtos com alto refund rate
    common_reasons: dict[str, int]  # Contagem por razão
    estimated_loss: float  # Perda estimada em R$


class RefundManager:
    """
    Manager para processar devoluções e reembolsos.
    
    Responsabilidades:
    - Listar devoluções pendentes
    - Avaliar e aprovar/rejeitar
    - Auto-remediation para casos críticos
    - Rastreamento de padrões
    """

    def __init__(self, history_dir: str = "reports"):
        """Inicializa manager de reembolsos."""
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.refund_file = self.history_dir / "laura_refunds_history.jsonl"
        self.stats_file = self.history_dir / "laura_refund_stats_latest.json"

        info("RefundManager initialized", history_dir=str(self.history_dir))

    def evaluate_refund(
        self,
        refund: Refund,
        product_data: dict[str, Any],
        buyer_history: dict[str, Any],
    ) -> RefundDecision:
        """
        Avalia uma devolução e retorna decisão automática.
        
        Lógica:
        - Se reembolso razão é óbvia (damaged, wrong item) → AUTO_APPROVE
        - Se compradora tem histórico bom → AUTO_APPROVE até 50% dos pedidos
        - Se muitos reembolsos para produto → AUTO_APPROVE (problema do produto)
        - Se padrão suspeito (many refunds from buyer) → MANUAL_REVIEW
        - Senão → CONTACT_BUYER (tentar resolver com cliente)
        
        Args:
            refund: Dados da devolução
            product_data: Dados do produto
            buyer_history: Histórico do comprador
        
        Returns:
            RefundDecision
        """

        # 1. Reembolsos óbvios
        if refund.reason in [
            RefundReason.DAMAGED_IN_TRANSIT,
            RefundReason.WRONG_ITEM,
            RefundReason.PRODUCT_DEFECTIVE,
        ]:
            debug("Auto-approving obvious refund", reason=refund.reason)
            return RefundDecision.AUTO_APPROVE

        # 2. Histórico de comprador
        orders_count = buyer_history.get("total_orders", 1)
        refunds_count = buyer_history.get("total_refunds", 0)
        refund_rate = (refunds_count + 1) / max(orders_count, 1) * 100  # +1 for this refund

        # Buyer bom: refund rate < 5%
        if refund_rate < 5.0:
            debug("Auto-approving for good buyer", refund_rate=refund_rate)
            return RefundDecision.AUTO_APPROVE

        # Buyer suspeito: refund rate > 20%
        if refund_rate > 20.0:
            warning("Suspicious buyer pattern", buyer_id=refund.buyer_id, refund_rate=refund_rate)
            return RefundDecision.MANUAL_REVIEW

        # 3. Padrão de produto
        product_refund_rate = product_data.get("refund_rate_pct", 0)
        if product_refund_rate > 15.0:
            debug("High refund product, approving", product_id=refund.product_id, rate=product_refund_rate)
            return RefundDecision.AUTO_APPROVE

        # 4. Default: tentar resolver com cliente
        return RefundDecision.CONTACT_BUYER

    def process_refund(
        self,
        refund: Refund,
        decision: RefundDecision,
        send_message: bool = True,
    ) -> dict[str, Any]:
        """
        Processa uma devolução conforme decisão.
        
        Args:
            refund: Dados da devolução
            decision: Decisão automática
            send_message: Se deve enviar mensagem ao comprador
        
        Returns:
            Resultado do processamento
        """
        result = {
            "refund_id": refund.refund_id,
            "decision": decision.value,
            "status": "processed",
            "timestamp": datetime.now(UTC).isoformat(),
            "message_sent": False,
            "actions": [],
        }

        if decision == RefundDecision.AUTO_APPROVE:
            result["actions"].append("approve_refund")
            result["actions"].append("process_payment")
            refund.status = RefundStatus.APPROVED
            if send_message:
                result["actions"].append("send_approval_message")
                result["message_sent"] = True

        elif decision == RefundDecision.AUTO_REJECT:
            result["actions"].append("reject_refund")
            refund.status = RefundStatus.REJECTED
            if send_message:
                result["actions"].append("send_rejection_message")
                result["message_sent"] = True

        elif decision == RefundDecision.CONTACT_BUYER:
            result["actions"].append("send_inquiry_message")
            result["message_sent"] = True

        elif decision == RefundDecision.MANUAL_REVIEW:
            result["actions"].append("flag_for_review")

        # Log refund
        self._log_refund(refund)

        return result

    def get_refund_stats(self, days: int = 30) -> RefundStats:
        """Calcula estatísticas de reembolsos."""
        if not self.refund_file.exists():
            return RefundStats(
                total_refunds=0,
                pending_count=0,
                approval_rate=0.0,
                avg_resolution_time_hours=0.0,
                high_refund_products=[],
                common_reasons={},
                estimated_loss=0.0,
            )

        refunds = []
        with open(self.refund_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        refunds.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Filter by date
        cutoff = datetime.now(UTC) - timedelta(days=days)
        recent = [
            r for r in refunds
            if datetime.fromisoformat(r["requested_at"]) >= cutoff
        ]

        if not recent:
            return RefundStats(
                total_refunds=0,
                pending_count=0,
                approval_rate=0.0,
                avg_resolution_time_hours=0.0,
                high_refund_products=[],
                common_reasons={},
                estimated_loss=0.0,
            )

        # Calculations
        pending = [r for r in recent if r["status"] == RefundStatus.PENDING.value]
        approved = [r for r in recent if r["status"] == RefundStatus.APPROVED.value]
        approval_rate = len(approved) / max(len(recent), 1) * 100

        # Resolution time
        resolved = [
            r for r in recent
            if r.get("resolved_at")
        ]
        if resolved:
            times = []
            for r in resolved:
                requested = datetime.fromisoformat(r["requested_at"])
                resolved_dt = datetime.fromisoformat(r["resolved_at"])
                times.append((resolved_dt - requested).total_seconds() / 3600)
            avg_time = sum(times) / len(times)
        else:
            avg_time = 0.0

        # Reasons
        reasons = {}
        for r in recent:
            reason = r.get("reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1

        # Estimated loss
        total_loss = sum(r.get("amount", 0) for r in approved)

        # Produtos com alto refund rate (top 5 por frequencia)
        from collections import Counter
        product_counts = Counter()
        product_names = {}
        for r in recent:
            pid = r.get("item_id") or r.get("product_id", "unknown")
            product_counts[pid] += 1
            if pid not in product_names:
                product_names[pid] = r.get("item_name", r.get("product_name", f"ID:{pid}"))
        total_recent = len(recent) or 1
        high_refund_products = [
            {"id": pid, "name": product_names[pid], "count": cnt, "pct": round(cnt / total_recent * 100, 1)}
            for pid, cnt in product_counts.most_common(5)
        ]

        return RefundStats(
            total_refunds=len(recent),
            pending_count=len(pending),
            approval_rate=approval_rate,
            avg_resolution_time_hours=avg_time,
            high_refund_products=high_refund_products,
            common_reasons=reasons,
            estimated_loss=total_loss,
        )

    def _log_refund(self, refund: Refund) -> None:
        """Registra reembolso no histórico."""
        with open(self.refund_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(refund), ensure_ascii=False, default=str) + "\n")

    def get_history(self, limit: int = 100, status_filter: str | None = None) -> list[dict]:
        """Retorna histórico de reembolsos."""
        if not self.refund_file.exists():
            return []

        refunds = []
        with open(self.refund_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        r = json.loads(line)
                        if status_filter and r.get("status") != status_filter:
                            continue
                        refunds.append(r)
                    except json.JSONDecodeError:
                        continue

        return refunds[-limit:]


def create_refund_manager() -> RefundManager:
    """Factory para criar manager de reembolsos."""
    return RefundManager()
