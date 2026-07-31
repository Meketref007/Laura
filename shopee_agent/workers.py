"""
Event workers for Event-Driven Architecture (Phase 36).

Provides BaseWorker with lifecycle hooks and specialized workers
that subscribe to EventBus events.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .decision_engine import Decision, DecisionType
from .event_bus import (
    AlertEvent,
    AsyncEventBus,
    CycleCompleteEvent,
    DecisionExecutedEvent,
    DecisionSignalEvent,
    Event,
    MetricUpdateEvent,
    OutcomeRecordedEvent,
)
from .logger import debug, info, warning


class BaseWorker(ABC):
    """Abstract worker with lifecycle hooks and event subscriptions."""

    def __init__(self, name: str, bus: AsyncEventBus):
        self.name = name
        self.bus = bus
        self._events_processed = 0

    def subscribe(self) -> None:
        """Register event handlers with the bus. Override to subscribe."""
        pass

    def on_start(self) -> None:
        """Called when the bus starts."""
        pass

    def on_stop(self) -> None:
        """Called when the bus stops."""
        pass

    def _handler_wrapper(self, event: Event) -> None:
        try:
            self.handle(event)
            self._events_processed += 1
        except Exception as exc:
            warning(f"Worker {self.name} failed on {event.event_type}", error=str(exc))

    @abstractmethod
    def handle(self, event: Event) -> None:
        """Process a single event. Must be implemented by subclasses."""
        ...


class DecisionWorker(BaseWorker):
    """Processes decision signals, executes approved low-priority decisions,
    and records outcomes."""

    def __init__(self, bus: AsyncEventBus, engine=None, executor=None, integrator=None, store_id: str = "default"):
        super().__init__("decision", bus)
        self.engine = engine
        self.executor = executor
        self.integrator = integrator
        self.store_id = store_id
        self.memory = None

    def subscribe(self) -> None:
        self.bus.register_handler("decision.signal", self._handler_wrapper)
        self.bus.register_handler("cycle.complete", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        if isinstance(event, DecisionSignalEvent):
            self._process_signal(event)
        elif isinstance(event, CycleCompleteEvent):
            self._process_pending(event)

    def _process_signal(self, event: DecisionSignalEvent) -> None:
        if not self.engine or not event.signal:
            return
        from .decision_engine import DecisionStatus
        decisions = self.engine.process_signal(event.signal, event.context)
        for d in decisions:
            if d.status == DecisionStatus.APPROVED:
                self._try_execute(d)

    def _process_pending(self, event: CycleCompleteEvent) -> None:
        if not self.engine:
            return
        from .decision_engine import DecisionPriority, DecisionStatus
        for d in list(self.engine.pending_decisions.values()):
            if d.status == DecisionStatus.APPROVED and d.priority == DecisionPriority.LOW:
                self._try_execute(d)

    def _try_execute(self, decision) -> None:
        if not self.executor or not self.integrator:
            return
        try:
            success = self.executor.execute(decision)
            if success:
                self.integrator.mark_decision_executed(decision.decision_id)
                info(f"DecisionWorker executed {decision.decision_id}")
                self.bus.submit(DecisionExecutedEvent(
                    event_type="decision.executed",
                    decision_id=decision.decision_id,
                    rule_id=decision.rule_id if hasattr(decision, "rule_id") else "",
                    status="executed",
                ))
        except Exception as exc:
            warning(f"DecisionWorker execute failed {decision.decision_id}", error=str(exc))
            self.bus.submit(DecisionExecutedEvent(
                event_type="decision.executed",
                decision_id=decision.decision_id,
                rule_id=decision.rule_id if hasattr(decision, "rule_id") else "",
                status="failed",
            ))


class OutcomeWorker(BaseWorker):
    """Processes outcome events, triggers adaptive rule learning,
    and persists aggregated metrics."""

    def __init__(self, bus: AsyncEventBus, engine=None, memory_layer=None):
        super().__init__("outcome", bus)
        self.engine = engine
        self.memory = memory_layer
        self._reports_dir = Path("reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_file = self._reports_dir / "effectiveness_metrics.jsonl"

    def subscribe(self) -> None:
        self.bus.register_handler("outcome.recorded", self._handler_wrapper)
        self.bus.register_handler("cycle.complete", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        if isinstance(event, OutcomeRecordedEvent):
            self._process_outcome(event)
        elif isinstance(event, CycleCompleteEvent):
            self._periodic_adjust()

    def _process_outcome(self, event: OutcomeRecordedEvent) -> None:
        if not self.memory:
            return
        from .decision_memory import DecisionOutcome
        outcome = DecisionOutcome(
            decision_id=event.decision_id,
            rule_id=event.rule_id,
            outcome_type=event.outcome_type,
            impact_realized=event.impact_realized,
            metadata=event.metadata,
            executed_at=event.timestamp or datetime.now(UTC),
        )
        self.memory.remember_outcome(outcome)
        debug(f"OutcomeWorker recorded {event.decision_id} -> {event.outcome_type}")

        if self.engine and event.rule_id in self.engine.rules:
            rule = self.engine.rules[event.rule_id]
            eff = self.memory.get_rule_effectiveness(event.rule_id)
            rule.last_success_rate = eff
            rule.adjust_based_on_outcomes(eff)
            self._persist_metrics(event)

    def _persist_metrics(self, event: OutcomeRecordedEvent) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "decision_id": event.decision_id,
            "rule_id": event.rule_id,
            "outcome_type": event.outcome_type,
            "impact_realized": event.impact_realized,
        }
        if self.engine and event.rule_id in self.engine.rules:
            rule = self.engine.rules[event.rule_id]
            entry["effectiveness_score"] = getattr(rule, "effectiveness_score", 0.0)
            entry["priority_boost"] = getattr(rule, "priority_boost", 0.0)
        with self._metrics_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _periodic_adjust(self) -> None:
        if not self.engine or not self.memory:
            return
        for rule_id, rule in self.engine.rules.items():
            eff = self.memory.get_rule_effectiveness(rule_id)
            rule.last_success_rate = eff
            rule.adjust_based_on_outcomes(eff)
        info("OutcomeWorker periodic adjustment complete", rules_updated=len(self.engine.rules))


class NotificationWorker(BaseWorker):
    """Dispatches alert events to Telegram and other notification channels."""

    def __init__(self, bus: AsyncEventBus, telegram_sender=None):
        super().__init__("notification", bus)
        self.telegram = telegram_sender

    def subscribe(self) -> None:
        self.bus.register_handler("alert", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        if isinstance(event, AlertEvent):
            self._send_alert(event)

    def _send_alert(self, event: AlertEvent) -> None:
        if not self.telegram:
            return
        icon = {"critical": "🚨", "error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(event.severity, "ℹ️")
        tags_str = f" [{', '.join(event.tags)}]" if event.tags else ""
        text = f"{icon} <b>{event.title}</b>{tags_str}\n{event.message}"
        try:
            self.telegram(text)
            debug(f"NotificationWorker sent alert: {event.title}")
        except Exception as exc:
            warning("NotificationWorker failed to send alert", error=str(exc))


class MetricWorker(BaseWorker):
    """Aggregates and exposes system metrics from events."""

    def __init__(self, bus: AsyncEventBus):
        super().__init__("metric", bus)
        self._metrics: dict[str, Any] = {
            "total_decisions": 0,
            "total_outcomes": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_alerts": 0,
            "cycles_completed": 0,
        }
        self._reports_dir = Path("reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def subscribe(self) -> None:
        self.bus.register_handler("decision.executed", self._handler_wrapper)
        self.bus.register_handler("outcome.recorded", self._handler_wrapper)
        self.bus.register_handler("cycle.complete", self._handler_wrapper)
        self.bus.register_handler("alert", self._handler_wrapper)
        self.bus.register_handler("metric.update", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        if isinstance(event, DecisionExecutedEvent):
            self._metrics["total_decisions"] += 1
        elif isinstance(event, OutcomeRecordedEvent):
            self._metrics["total_outcomes"] += 1
            if event.outcome_type == "success":
                self._metrics["success_count"] += 1
            elif event.outcome_type == "failure":
                self._metrics["failure_count"] += 1
        elif isinstance(event, CycleCompleteEvent):
            self._metrics["cycles_completed"] += 1
        elif isinstance(event, AlertEvent):
            self._metrics["total_alerts"] += 1
        elif isinstance(event, MetricUpdateEvent):
            self._metrics.update(event.metrics)

    def get_metrics(self) -> dict[str, Any]:
        return dict(self._metrics)

    def get_success_rate(self) -> float:
        total = self._metrics["success_count"] + self._metrics["failure_count"]
        if total == 0:
            return 0.0
        return self._metrics["success_count"] / total


class OrchestrationWorker(BaseWorker):
    """Phase 37: Runs AgentOrchestrator on cycle events and executes approved actions."""

    def __init__(self, bus: AsyncEventBus, executor: Any | None = None):
        super().__init__("orchestration", bus)
        self._reports_dir = Path("reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._plans_file = self._reports_dir / "orchestration_plans.jsonl"
        self._executor = executor

    def subscribe(self) -> None:
        self.bus.register_handler("cycle.complete", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        if not isinstance(event, CycleCompleteEvent):
            return
        if event.cycle_number % 24 != 0:
            return
        try:
            from shopee_agent.agent_orchestrator import AgentOrchestrator
            from shopee_agent.decision_engine import default_economic_context
            ctx = default_economic_context()
            orchestrator = AgentOrchestrator()
            plan = orchestrator.coordinate_cycle_sync(ctx)

            executed = 0
            failed = 0
            for action in plan.approved_actions:
                success = self._execute_action(action)
                if success:
                    executed += 1
                else:
                    failed += 1

            entry = {
                "timestamp": datetime.now(UTC).isoformat(),
                "cycle": event.cycle_number,
                "plan_id": plan.plan_id,
                "approved": len(plan.approved_actions),
                "executed": executed,
                "failed": failed,
                "rejected": len(plan.rejected_actions),
                "conflicts": len(plan.conflicts),
                "consensus_score": plan.consensus_score,
            }
            with self._plans_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            info("Orchestration plan executed", plan_id=plan.plan_id, executed=executed)
        except Exception as exc:
            warning("OrchestrationWorker failed", error=str(exc))

    def _execute_action(self, action: Any) -> bool:
        """Map an AgentAction to a DecisionExecutor call or direct API."""
        executor = self._executor
        if executor is not None:
            from shopee_agent.decision_engine import Decision, DecisionType
            action_type_str = getattr(action, "action_type", "") or ""
            if "price" in action_type_str.lower():
                dt = DecisionType.PRICING
            elif "ad" in action_type_str.lower() or "budget" in action_type_str.lower():
                dt = DecisionType.ADS
            elif "stock" in action_type_str.lower() or "inventory" in action_type_str.lower():
                dt = DecisionType.INVENTORY
            else:
                dt = DecisionType.ALERTS

            dec = Decision(
                decision_id=getattr(action, "action_id", f"orch_{id(action)}"),
                decision_type=dt,
                title=f"{getattr(action, 'agent_name', '?')}: {action_type_str} on {getattr(action, 'target', '?')}",
                description=getattr(action, "rationale", ""),
                priority=getattr(action, "priority", 3),
                status="pending",
                metadata={
                    "agent": getattr(action, "agent_name", ""),
                    "target": getattr(action, "target", ""),
                    "direction": getattr(action, "direction", ""),
                    "magnitude": getattr(action, "magnitude", 0),
                    "source": "orchestration_worker",
                },
            )
            try:
                return executor.execute(dec)
            except Exception as e:
                warning(f"OrchestrationWorker executor failed for {dec.decision_id}", error=str(e))
                return False

        info(f"OrchestrationWorker no executor, would execute {action}")
        return True


class PlanningWorker(BaseWorker):
    """Phase 38: Runs StrategicPlanner on cycle events and executes plan phases."""

    def __init__(self, bus: AsyncEventBus, executor: Any | None = None):
        super().__init__("planning", bus)
        self._reports_dir = Path("reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._plans_file = self._reports_dir / "strategic_plans.jsonl"
        self._executor = executor

    def subscribe(self) -> None:
        self.bus.register_handler("cycle.complete", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        if not isinstance(event, CycleCompleteEvent):
            return
        if event.cycle_number % 48 != 0:
            return
        try:
            from shopee_agent.decision_engine import default_economic_context
            from shopee_agent.strategic_planner import GoalStack, StrategicPlanner
            ctx = default_economic_context()
            planner = StrategicPlanner()
            goals = GoalStack()
            result = planner.create_and_assess(goals, ctx)
            plan = result.get("plan")
            if plan:
                executed_phases = self._execute_phases(plan)
                entry = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "cycle": event.cycle_number,
                    "plan_id": plan.plan_id,
                    "name": plan.name,
                    "status": plan.status.value,
                    "phases": len(plan.phases),
                    "executed_phases": executed_phases,
                    "budget": plan.budget,
                    "objective": plan.objective,
                }
                with self._plans_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                info("Strategic plan executed", plan_id=plan.plan_id, phases=executed_phases)
        except Exception as exc:
            warning("PlanningWorker failed", error=str(exc))

    def _execute_phases(self, plan: Any) -> int:
        """Execute actionable phases from a strategic plan.
        Returns number of phases successfully dispatched.
        """
        executor = self._executor
        phases = getattr(plan, "phases", [])
        executed = 0
        for phase in phases:
            phase_name = getattr(phase, "name", "") or getattr(phase, "objective", "") or str(phase)
            if executor is not None:
                dec = Decision(
                    decision_id=f"strat_{plan.plan_id}_{executed}",
                    decision_type=DecisionType.ALERTS,
                    title=f"Strategic: {phase_name}",
                    description=getattr(phase, "description", ""),
                    priority=2,
                    status="pending",
                    metadata={
                        "plan_id": plan.plan_id,
                        "phase": phase_name,
                        "source": "planning_worker",
                    },
                )
                try:
                    if executor.execute(dec):
                        executed += 1
                except Exception as e:
                    warning(f"PlanningWorker phase execution failed for {phase_name}", error=str(e))
            else:
                executed += 1
        return executed


class RefundWorker(BaseWorker):
    """Processes refund events through RefundManager and emits decisions."""

    def __init__(self, bus: AsyncEventBus, refund_manager=None):
        super().__init__("refund", bus)
        self._refund_manager = refund_manager

    def _get_manager(self):
        if self._refund_manager is None:
            from .refunds import RefundManager
            self._refund_manager = RefundManager()
        return self._refund_manager

    def subscribe(self) -> None:
        self.bus.register_handler("refund", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        from .event_bus import RefundEvent
        if not isinstance(event, RefundEvent):
            return
        manager = self._get_manager()
        from datetime import datetime

        from .refunds import Refund, RefundReason, RefundStatus
        try:
            reason = RefundReason(event.refund_reason)
        except ValueError:
            reason = RefundReason.OTHER
        refund = Refund(
            refund_id=event.refund_id,
            order_id=event.order_id or event.refund_id,
            buyer_id=event.buyer_id,
            product_id=event.product_id,
            reason=reason,
            status=RefundStatus(event.status) if event.status else RefundStatus.PENDING,
            amount=event.amount,
            requested_at=event.requested_at or datetime.now(UTC).isoformat(),
        )
        decision = manager.evaluate_refund(refund, product_data={}, buyer_history={})
        result = manager.process_refund(refund, decision=decision)
        decision_str = result.get("decision", decision.value)
        info(f"RefundWorker processed {event.refund_id}", decision=decision_str)
        self.bus.submit(
            __import__("shopee_agent.event_bus", fromlist=["AlertEvent"]).AlertEvent(
                event_type="alert",
                severity="warning" if decision_str == "manual_review" else "info",
                title=f"Refund: {event.refund_id[:12]}",
                message=f"Decision: {decision_str}\nReason: {event.refund_reason}\nAmount: ${event.amount:.2f}",
                tags=["refund"],
            )
        )


class AutoSkillWorker(BaseWorker):
    """Periodically uses SkillOrchestrator (GOAP) to select and execute skills."""

    def __init__(
        self,
        bus: AsyncEventBus,
        registry=None,
        interval_seconds: int = 300,
        max_skills_per_cycle: int = 3,
        dry_run: bool = False,
    ):
        super().__init__("auto_skill", bus)
        self.registry = registry
        self.interval = interval_seconds
        self.max_per_cycle = max_skills_per_cycle
        self.dry_run = dry_run
        self._last_run: datetime | None = None

    def subscribe(self) -> None:
        self.bus.register_handler("cycle.complete", self._handler_wrapper)

    def handle(self, event: Event) -> None:
        now = datetime.now(UTC)
        if self._last_run and (now - self._last_run).total_seconds() < self.interval:
            return
        self._last_run = now
        self._run_applicable_skills()

    def _run_applicable_skills(self) -> None:
        from shopee_agent.skills.loader import discover_and_register
        discover_and_register()

        registry = self.registry or __import__("shopee_agent.skills.registry", fromlist=["default_registry"]).default_registry
        if not registry._skills:
            debug("AutoSkillWorker: no skills registered")
            return

        from shopee_agent.skills.orchestrator import SkillOrchestrator
        orchestrator = SkillOrchestrator(registry=registry, event_bus=self.bus)

        current_state = self._collect_state()
        goal_state = {
            "stock_checked": True,
            "margin_protected": True,
            "orders_pending_ship": False,
            "support_handled": True,
        }

        result = orchestrator.evaluate_state(
            current_state, goal_state, max_depth=4,
            dry_run=self.dry_run, timeout_seconds=15.0,
        )
        if result["status"] in ("executed", "dry_run"):
            ok_count = sum(1 for r in result["results"] if r["ok"])
            info(f"AutoSkillWorker: {ok_count}/{len(result['skills'])} skills ok (mode={result['status']})")
            if ok_count < len(result["results"]):
                for r in result["results"]:
                    if not r["ok"]:
                        warning("AutoSkillWorker skill failed", skill=r["skill"], error=r.get("error"))
        else:
            debug(f"AutoSkillWorker: {result['status']}")

    def _collect_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        try:
            reports_dir = Path("reports")
            prices_file = reports_dir / "product_prices.json"
            if prices_file.exists():
                data = json.loads(prices_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    state["prices"] = data
            orders_log = reports_dir / "laura_autonomous_log.jsonl"
            if orders_log.exists():
                lines = orders_log.read_text(encoding="utf-8").splitlines()
                recent = [json.loads(l) for l in lines[-5:] if l.strip()]
                if any(
                    r.get("state_summary", {}).get("orders_seen", 0) > 0
                    for r in recent if isinstance(r, dict)
                ):
                    state["orders_pending_ship"] = True
        except Exception:
            pass
        return state
