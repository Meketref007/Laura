"""
Decision Engine v1 for Laura
==============================

Central autonomous decision-making system that:
1. Receives operational signals (metrics, alerts, state)
2. Evaluates decision rules against guardrails
3. Generates prioritized actions with impact/risk scores
4. Maintains full auditability of decisions

Architecture:
- Signal Processor: Aggregates input from monitoring/alerts/metrics
- Decision Evaluator: Applies rule engine + economic model
- Action Generator: Creates execution plans with priority/deadline
- Audit Logger: Records all decisions with reasoning

This bridges the gap between distributed automation (current)
and centralized agentic reasoning (target).

Author: Laura Decision Engine
Date: 2026-05-14
Status: v1.0 - MVP for Phase 34
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from shopee_agent.decision_memory import DecisionOutcome, MemoryLayer
from shopee_agent.paths import DECISION_LOG

logger = logging.getLogger("laura.decision_engine")


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class DecisionType(Enum):
    """Categories of autonomous decisions."""
    PRICING = "pricing"  # Dynamic price/discount adjustments
    ADS = "ads"  # Campaign pause/resume, budget allocation
    INVENTORY = "inventory"  # Restocking, warehouse allocation
    CUSTOMER_SERVICE = "customer_service"  # Auto-response policies
    ALERTS = "alerts"  # Alert routing and escalation
    EXPERIMENTS = "experiments"  # A/B test execution
    METADATA = "metadata"  # Product info, category changes


class DecisionPriority(Enum):
    """Priority levels for action execution."""
    CRITICAL = 1  # Financial risk, compliance, safety
    HIGH = 2  # Revenue/margin opportunity, customer impact
    NORMAL = 3  # Routine optimizations
    LOW = 4  # Nice-to-have improvements


class DecisionStatus(Enum):
    """Lifecycle state of a decision."""
    PENDING = "pending"  # Created, awaiting approval/scheduling
    APPROVED = "approved"  # Passed guardrails, ready for execution
    REJECTED = "rejected"  # Violates guardrails
    EXECUTED = "executed"  # Actioned in production
    REVERTED = "reverted"  # Rolled back due to negative result


class RiskLevel(Enum):
    """Risk assessment of a decision."""
    NEGLIGIBLE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class DecisionSignal:
    """Input signal that triggers decision evaluation."""
    source: str  # "metrics", "alerts", "webhook", "manual", "scheduled"
    signal_type: str  # "anomaly", "opportunity", "risk", "routine"
    data: dict[str, Any]  # Signal payload
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    context: dict[str, Any] | None = None  # Additional context


@dataclass
class DecisionRule:
    """Condition + action pair for decision logic."""
    rule_id: str
    decision_type: DecisionType
    name: str
    description: str

    # Evaluation
    condition: str  # Semantic description of when this rule applies
    priority_boost: int = 0  # Priority adjustment if this rule matches

    # Guard rails
    risk_threshold: RiskLevel = RiskLevel.MEDIUM
    max_daily_executions: int | None = None
    min_hours_between_executions: int | None = None

    # Impact estimation
    estimated_impact: dict[str, float] = field(default_factory=dict)  # {"margin": 0.05, "roas": 0.08}

    # Metadata
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    modified_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Adaptive fields (updated by learning layer)
    effectiveness_score: float = 0.5  # 0-1 based on outcome success rate
    last_success_rate: float = 0.5    # Recent success rate
    adjusted_thresholds: dict[str, float] = field(default_factory=dict)
    execution_count: int = 0

    def adjust_based_on_outcomes(self, success_rate: float) -> None:
        """Adjust rule parameters based on observed success rate."""
        self.last_success_rate = success_rate
        self.effectiveness_score = 0.7 * self.effectiveness_score + 0.3 * success_rate
        # Boost priority for effective rules, reduce for failing ones
        if success_rate > 0.6:
            self.priority_boost = min(10, self.priority_boost + 1)
        elif success_rate < 0.3:
            self.priority_boost = max(0, self.priority_boost - 1)
        self.modified_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "decision_type": self.decision_type.value,
            "name": self.name,
            "description": self.description,
            "condition": self.condition,
            "priority_boost": self.priority_boost,
            "risk_threshold": self.risk_threshold.name,
            "max_daily_executions": self.max_daily_executions,
            "min_hours_between_executions": self.min_hours_between_executions,
            "estimated_impact": self.estimated_impact,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "effectiveness_score": self.effectiveness_score,
            "last_success_rate": self.last_success_rate,
            "adjusted_thresholds": self.adjusted_thresholds,
            "execution_count": self.execution_count,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "DecisionRule":
        dt = DecisionType(d.get("decision_type")) if d.get("decision_type") else DecisionType.METADATA
        risk = RiskLevel[d.get("risk_threshold")] if d.get("risk_threshold") in RiskLevel.__members__ else RiskLevel.MEDIUM
        created = None
        modified = None
        try:
            if d.get("created_at"):
                created = datetime.fromisoformat(d.get("created_at")).replace(tzinfo=None)
        except Exception:
            created = None
        try:
            if d.get("modified_at"):
                modified = datetime.fromisoformat(d.get("modified_at")).replace(tzinfo=None)
        except Exception:
            modified = None

        return DecisionRule(
            rule_id=d.get("rule_id", ""),
            decision_type=dt,
            name=d.get("name", ""),
            description=d.get("description", ""),
            condition=d.get("condition", ""),
            priority_boost=int(d.get("priority_boost", 0)),
            risk_threshold=risk,
            max_daily_executions=d.get("max_daily_executions"),
            min_hours_between_executions=d.get("min_hours_between_executions"),
            estimated_impact=d.get("estimated_impact", {}),
            enabled=bool(d.get("enabled", True)),
            created_at=created or datetime.now(UTC),
            modified_at=modified or datetime.now(UTC),
            effectiveness_score=float(d.get("effectiveness_score", 0.5)),
            last_success_rate=float(d.get("last_success_rate", 0.5)),
            adjusted_thresholds=d.get("adjusted_thresholds", {}),
            execution_count=int(d.get("execution_count", 0)),
        )


@dataclass
class Decision:
    """Core decision object with full context and auditability."""
    decision_id: str
    decision_type: DecisionType
    rule_id: str

    # Content
    title: str
    description: str
    recommended_action: str  # Natural language action

    # Scoring
    priority: DecisionPriority
    impact_score: float  # -1.0 to 1.0 (negative risk, positive opportunity)
    risk_score: float  # 0.0 to 1.0 (probability of negative outcome)
    confidence_score: float  # 0.0 to 1.0 (model confidence in this decision)

    # Context
    signal: DecisionSignal
    guardrails_passed: dict[str, bool] = field(default_factory=dict)

    # State
    status: DecisionStatus = DecisionStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    executed_at: datetime | None = None

    # Audit trail
    reasoning: str = ""  # Why this decision was made
    assumptions: list[str] = field(default_factory=list)
    alternative_actions: list[str] = field(default_factory=list)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        data = asdict(self)
        data["decision_type"] = self.decision_type.value
        data["priority"] = self.priority.value
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["executed_at"] = self.executed_at.isoformat() if self.executed_at else None
        data["signal"]["timestamp"] = self.signal.timestamp.isoformat()
        return data


@dataclass
class EconomicContext:
    """Current economic state for decision-making."""
    current_margin_pct: float
    margin_target_pct: float
    daily_revenue_usd: float
    cash_buffer_usd: float
    inventory_days_on_hand: int
    stock_risk_level: str  # "critical", "high", "normal", "excess"
    active_promotions: int
    advertising_spend_daily_usd: float
    advertising_roas: float
    customer_satisfaction_score: float  # 0-100
    recent_anomalies: list[str]

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


def default_economic_context(**overrides: Any) -> EconomicContext:
    """Centralized factory para EconomicContext com valores default seguros.
    Tenta ler dados reais de reports/*.json se disponiveis.
    """
    base = dict(
        current_margin_pct=35.0,
        margin_target_pct=20.0,
        daily_revenue_usd=5000.0,
        cash_buffer_usd=30000.0,
        inventory_days_on_hand=14,
        stock_risk_level="low",
        active_promotions=0,
        advertising_spend_daily_usd=100.0,
        advertising_roas=2.1,
        customer_satisfaction_score=80.0,
        recent_anomalies=[],
    )
    _try_load_real_data(base)
    base.update(overrides)
    return EconomicContext(**base)


def _try_load_real_data(base: dict[str, Any]) -> None:
    """Tenta enriquecer base com dados reais dos reports."""
    reports = Path("reports")
    if not reports.exists():
        return
    try:
        pf = reports / "laura_profitability_latest.json"
        if pf.exists():
            with pf.open() as f:
                p = json.load(f)
            if "gross_margin_pct" in p:
                base["current_margin_pct"] = float(p["gross_margin_pct"])
            if "actual_roas" in p:
                base["advertising_roas"] = float(p["actual_roas"])
            if "daily_revenue_usd" in p:
                base["daily_revenue_usd"] = float(p["daily_revenue_usd"])
    except Exception:
        pass
    try:
        sf = reports / "laura_profitability_state.json"
        if sf.exists():
            with sf.open() as f:
                s = json.load(f)
            if "cash_buffer_usd" in s:
                base["cash_buffer_usd"] = float(s["cash_buffer_usd"])
            if "inventory_doh" in s:
                base["inventory_days_on_hand"] = int(s["inventory_doh"])
            if "inventory_status" in s:
                base["stock_risk_level"] = str(s["inventory_status"])
            if "active_promotions" in s:
                base["active_promotions"] = int(s["active_promotions"])
    except Exception:
        pass
    try:
        mf = reports / "laura_metrics.jsonl"
        if mf.exists():
            anomalies = []
            with mf.open() as f:
                lines = f.readlines()[-10:]
            for line in lines:
                try:
                    m = json.loads(line)
                    if m.get("status") == "anomaly":
                        anomalies.append(str(m.get("type", "unknown")))
                except Exception:
                    continue
            if anomalies:
                base["recent_anomalies"] = anomalies
    except Exception:
        pass


# ============================================================================
# DECISION ENGINE CORE
# ============================================================================

class DecisionEngine:
    """
    Central decision-making system for Laura.
    
    Responsibilities:
    1. Ingest signals from monitoring/metrics/alerts
    2. Evaluate against rules and guardrails
    3. Generate prioritized decisions
    4. Maintain audit trail
    5. Track decision outcomes for learning
    """

    def __init__(
        self,
        store_id: str = "default",
        rules: list[DecisionRule] | None = None,
        log_path: str = str(DECISION_LOG),
        memory: MemoryLayer | None = None,
    ):
        self.store_id = store_id
        self.rules = {r.rule_id: r for r in (rules or [])}
        self.log_path = log_path
        self.pending_decisions: dict[str, Decision] = {}
        self.decision_history: list[Decision] = []
        # Optional memory layer for Phase 35
        self.memory = memory
        self._pending_path = Path("reports") / f"pending_decisions_{store_id}.jsonl"

        self._load_pending()

        logger.info(f"DecisionEngine initialized for store {store_id} with {len(self.rules)} rules")

    def _load_pending(self) -> None:
        if not self._pending_path.exists():
            return
        try:
            with self._pending_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        sig_data = data.pop("_signal", {})
                        sig = DecisionSignal(
                            source=sig_data.get("source", ""),
                            signal_type=sig_data.get("signal_type", ""),
                            data=sig_data.get("data", {}),
                        )
                        d = Decision(
                            decision_id=data.get("decision_id", ""),
                            decision_type=DecisionType(data.get("decision_type", "alerts")),
                            rule_id=data.get("rule_id", ""),
                            title=data.get("title", ""),
                            description=data.get("description", ""),
                            recommended_action=data.get("recommended_action", ""),
                            priority=DecisionPriority(data.get("priority", 4)),
                            impact_score=float(data.get("impact_score", 0.0)),
                            risk_score=float(data.get("risk_score", 0.0)),
                            confidence_score=float(data.get("confidence_score", 0.0)),
                            signal=sig,
                        )
                        d.status = DecisionStatus(data.get("status", "pending"))
                        d.metadata = data.get("metadata", {})
                        self.pending_decisions[d.decision_id] = d
                    except Exception:
                        continue
        except Exception:
            pass

    def _save_pending(self) -> None:
        try:
            self._pending_path.parent.mkdir(parents=True, exist_ok=True)
            with self._pending_path.open("w", encoding="utf-8") as f:
                for d in self.pending_decisions.values():
                    entry = d.to_dict()
                    entry["_signal"] = {"source": d.signal.source, "signal_type": d.signal.signal_type, "data": d.signal.data}
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def add_rule(self, rule: DecisionRule) -> None:
        """Register a new decision rule."""
        self.rules[rule.rule_id] = rule
        logger.info(f"Rule added: {rule.rule_id}")

    def process_signal(
        self,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> list[Decision]:
        """
        Process an incoming signal and generate decisions.
        
        Returns:
            List of generated decisions (may be empty if no rules match)
        """
        generated_decisions = []

        logger.info(
            f"Processing signal: {signal.source}/{signal.signal_type} "
            f"at {signal.timestamp}"
        )

        # Evaluate each rule
        for rule in self.rules.values():
            if not rule.enabled:
                continue

            # Simple rule matching (v1: based on signal type and source)
            if self._rule_applies(rule, signal, context):
                decision = self._generate_decision(rule, signal, context)

                # Evaluate guardrails
                guardrail_status = self._evaluate_guardrails(decision, context)
                decision.guardrails_passed = guardrail_status

                # Set status based on guardrails
                if all(guardrail_status.values()):
                    decision.status = DecisionStatus.APPROVED
                    logger.info(f"Decision APPROVED: {decision.decision_id}")
                else:
                    decision.status = DecisionStatus.REJECTED
                    logger.warning(
                        f"Decision REJECTED: {decision.decision_id} - "
                        f"Failed guardrails: {[k for k, v in guardrail_status.items() if not v]}"
                    )

                # Store
                self.pending_decisions[decision.decision_id] = decision
                generated_decisions.append(decision)

                self._log_decision(decision)

        self._save_pending()
        return generated_decisions

    def _rule_applies(
        self,
        rule: DecisionRule,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> bool:
        """
        Check if a rule matches the current signal and context.
        
        This is a simplified v1 implementation.
        In v2, this would use a more sophisticated rule engine (Drools, etc).
        """
        # Match by signal source and type
        rule_patterns = {
            DecisionType.PRICING: ["metrics", "anomaly"],
            DecisionType.ADS: ["metrics", "opportunity"],
            DecisionType.INVENTORY: ["metrics", "risk"],
        }

        if rule.decision_type not in rule_patterns:
            return False

        source_match = any(p in signal.source.lower() for p in rule_patterns[rule.decision_type])
        type_match = any(t in signal.signal_type.lower() for t in rule_patterns[rule.decision_type])

        return source_match and type_match

    def _generate_decision(
        self,
        rule: DecisionRule,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> Decision:
        """Generate a decision from a rule and signal."""
        decision_id = self._generate_id(rule.rule_id, signal)

        # Simple impact estimation (v1)
        impact = rule.estimated_impact.get("margin", 0.01)
        impact_score = max(-1.0, min(1.0, impact))
        risk_score = self._estimate_risk(rule, context)
        confidence = self._estimate_confidence(rule, signal, context)

        # Priority from rule + signal urgency
        priority = self._calculate_priority(rule, signal, context)

        decision = Decision(
            decision_id=decision_id,
            decision_type=rule.decision_type,
            rule_id=rule.rule_id,
            title=rule.name,
            description=rule.description,
            recommended_action=self._generate_action_text(rule, signal, context),
            priority=priority,
            impact_score=impact_score,
            risk_score=risk_score,
            confidence_score=confidence,
            signal=signal,
            reasoning=self._generate_reasoning(rule, signal, context),
            assumptions=[
                f"Current margin: {context.current_margin_pct:.1f}%",
                f"Margin target: {context.margin_target_pct:.1f}%",
                f"ROAS: {context.advertising_roas:.2f}",
            ],
        )

        return decision

    def _evaluate_guardrails(
        self,
        decision: Decision,
        context: EconomicContext,
    ) -> dict[str, bool]:
        """
        Check decision against financial and operational guardrails.
        
        Returns:
            Dict of guardrail_name -> passed (bool)
        """
        guardrails = {}

        # Economic guardrails
        guardrails["margin_floor"] = context.current_margin_pct >= (context.margin_target_pct * 0.8)
        guardrails["cash_buffer"] = context.cash_buffer_usd >= 1000  # Min $1k
        guardrails["inventory_healthy"] = context.stock_risk_level != "critical"

        # Risk guardrails
        guardrails["acceptable_risk"] = decision.risk_score <= 0.8

        # Operational guardrails
        guardrails["reasonable_confidence"] = decision.confidence_score >= 0.5

        # Decision-specific guardrails
        if decision.decision_type == DecisionType.PRICING:
            guardrails["not_overpricing"] = decision.impact_score > -0.5
        elif decision.decision_type == DecisionType.ADS:
            guardrails["roas_acceptable"] = context.advertising_roas >= 1.5

        return guardrails

    def _estimate_risk(self, rule: DecisionRule, context: EconomicContext) -> float:
        """Estimate probability of negative outcome."""
        base_risk = rule.risk_threshold.value / 5.0

        # Adjust based on context
        if context.stock_risk_level == "critical":
            base_risk += 0.2
        if context.recent_anomalies:
            base_risk += 0.1

        return min(1.0, base_risk)

    def _estimate_confidence(
        self,
        rule: DecisionRule,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> float:
        """Estimate model confidence in this decision."""
        base_confidence = 0.6

        # Higher confidence if signal strength is clear
        if signal.data.get("anomaly_severity", 0) > 0.5:
            base_confidence += 0.2

        # Lower confidence in high-uncertainty contexts
        if context.customer_satisfaction_score < 70:
            base_confidence -= 0.1

        return max(0.0, min(1.0, base_confidence))

    def _calculate_priority(
        self,
        rule: DecisionRule,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> DecisionPriority:
        """Calculate action priority."""
        # Start with signal urgency
        if signal.signal_type == "risk":
            base_priority = DecisionPriority.CRITICAL
        elif signal.signal_type == "anomaly":
            base_priority = DecisionPriority.HIGH
        else:
            base_priority = DecisionPriority.NORMAL

        # Adjust by context
        if context.stock_risk_level == "critical":
            return DecisionPriority.CRITICAL
        if context.margin_target_pct - context.current_margin_pct > 5:
            return DecisionPriority.HIGH

        return base_priority

    def _generate_action_text(
        self,
        rule: DecisionRule,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> str:
        """Generate human-readable action recommendation."""
        actions = {
            DecisionType.PRICING: f"Adjust pricing to improve margin (target: {context.margin_target_pct:.1f}%)",
            DecisionType.ADS: f"Optimize ad spend to improve ROAS (current: {context.advertising_roas:.2f})",
            DecisionType.INVENTORY: "Monitor inventory levels and plan restocking",
        }
        return actions.get(rule.decision_type, rule.description)

    def _generate_reasoning(
        self,
        rule: DecisionRule,
        signal: DecisionSignal,
        context: EconomicContext,
    ) -> str:
        """Generate explanation for this decision."""
        return (
            f"Rule '{rule.name}' triggered by signal {signal.signal_type}. "
            f"Current economic state: margin={context.current_margin_pct:.1f}%, "
            f"roas={context.advertising_roas:.2f}, "
            f"inventory_health={context.stock_risk_level}. "
            f"Decision type: {rule.decision_type.value}."
        )

    def _generate_id(self, rule_id: str, signal: DecisionSignal) -> str:
        """Generate unique decision ID."""
        seed = f"{rule_id}:{signal.timestamp.isoformat()}:{signal.source}"
        hash_digest = hashlib.md5(seed.encode()).hexdigest()[:8]
        return f"dec_{hash_digest}"

    def execute_decision(self, decision_id: str) -> bool:
        """
        Mark a decision as executed.
        
        In real implementation, this would:
        1. Validate decision still in APPROVED state
        2. Call appropriate action handler
        3. Record execution timestamp
        4. Update status to EXECUTED
        """
        if decision_id not in self.pending_decisions:
            logger.warning(f"Decision not found: {decision_id}")
            return False

        decision = self.pending_decisions[decision_id]

        if decision.status != DecisionStatus.APPROVED:
            logger.warning(f"Cannot execute decision in {decision.status.value} state")
            return False

        decision.status = DecisionStatus.EXECUTED
        decision.executed_at = datetime.now(UTC)

        logger.info(f"Decision executed: {decision_id}")
        self._log_decision(decision)
        # If memory is available, record a minimal outcome entry (will be enriched later)
        try:
            if self.memory:
                outcome = DecisionOutcome(
                    decision_id=decision.decision_id,
                    rule_id=decision.rule_id,
                    executed_at=decision.executed_at,
                    outcome_type="executed",
                    impact_realized=None,
                    metadata={
                        "decision_title": decision.title,
                        "decision_type": decision.decision_type.value,
                    },
                )
                # Try to produce a semantic vector for the outcome using the
                # local Ollama analyzer if available; otherwise use a simple
                # deterministic fallback embedder.
                vec = None
                try:
                    from .llm_local import LauraOllamaAnalyzer
                    analyzer = LauraOllamaAnalyzer(model=os.getenv("LAURA_LLM_MODEL", "llama3.2:3b"), pull_model=False)
                    vec = analyzer.embed_text(f"{outcome.rule_id} {outcome.metadata.get('decision_title','')}")
                except Exception:
                    vec = None

                if vec is None:
                    try:
                        from .vector_store import simple_text_to_vector
                        text = f"{outcome.rule_id} {outcome.metadata.get('decision_title','')}"
                        vec = simple_text_to_vector(text, dim=128)
                    except Exception:
                        vec = None

                if vec is not None:
                    try:
                        self.memory.remember_outcome_with_vector(outcome, vector=vec)
                    except Exception:
                        # fallback to plain storage if vector indexing fails
                        self.memory.remember_outcome(outcome)
                else:
                    self.memory.remember_outcome(outcome)
        except Exception:
            logger.exception("Failed to persist decision outcome to memory")

        self._save_pending()
        return True

    def _log_decision(self, decision: Decision) -> None:
        """Append decision to audit log."""
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(decision.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

    def get_pending_decisions(
        self,
        decision_type: DecisionType | None = None,
        min_priority: DecisionPriority | None = None,
    ) -> list[Decision]:
        """Retrieve pending decisions with optional filtering."""
        decisions = [d for d in self.pending_decisions.values()]

        if decision_type:
            decisions = [d for d in decisions if d.decision_type == decision_type]

        if min_priority:
            decisions = [d for d in decisions if d.priority.value <= min_priority.value]

        return sorted(decisions, key=lambda d: (d.priority.value, d.impact_score), reverse=True)

    def summary(self) -> dict[str, Any]:
        """Get engine status summary."""
        summary = {
            "store_id": self.store_id,
            "total_rules": len(self.rules),
            "pending_decisions": len(self.pending_decisions),
            "critical_decisions": len([d for d in self.pending_decisions.values() if d.priority == DecisionPriority.CRITICAL]),
            "total_decisions_logged": len(self.decision_history),
            "decision_log_path": self.log_path,
        }

        if self.memory is not None:
            recent_outcomes = self.memory.list_outcomes(limit=50)
            summary["memory_outcomes"] = len(recent_outcomes)
            summary["memory_recent_effectiveness"] = {
                outcome.rule_id: self.memory.get_rule_effectiveness(outcome.rule_id)
                for outcome in recent_outcomes[-5:]
            }

        return summary


# ============================================================================
# DEFAULT RULES
# ============================================================================

def create_default_rules() -> list[DecisionRule]:
    """Create initial set of decision rules for Phase 34."""
    return [
        DecisionRule(
            rule_id="pricing_margin_protect",
            decision_type=DecisionType.PRICING,
            name="Margin Protection Pricing",
            description="Adjust pricing when margin drops below target",
            condition="current_margin < target_margin * 0.9",
            priority_boost=1,
            risk_threshold=RiskLevel.LOW,
            estimated_impact={"margin": 0.03},
            enabled=True,
        ),
        DecisionRule(
            rule_id="ads_roas_optimize",
            decision_type=DecisionType.ADS,
            name="ROAS Optimization",
            description="Pause low-ROAS campaigns to improve efficiency",
            condition="campaign_roas < baseline_roas",
            priority_boost=0,
            risk_threshold=RiskLevel.MEDIUM,
            estimated_impact={"roas": 0.15},
            enabled=True,
        ),
        DecisionRule(
            rule_id="inventory_stockout_prevent",
            decision_type=DecisionType.INVENTORY,
            name="Stockout Prevention",
            description="Trigger restocking when inventory reaches critical levels",
            condition="days_on_hand < safety_stock",
            priority_boost=2,
            risk_threshold=RiskLevel.CRITICAL,
            max_daily_executions=1,
            estimated_impact={"stockout_risk": -0.5},
            enabled=True,
        ),
    ]
