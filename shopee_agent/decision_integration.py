"""
Decision Engine Integration with Laura Autonomous Loop

This module bridges:
- Metrics collection → Decision signals
- Profitability engine → Economic context
- Autopilot → Decision execution
- Monitoring → Alert signals

Architecture:
1. autonomous_loop.py runs its normal cycle (collect → analyze → act)
2. Metrics are now also fed to decision_engine
3. Decision engine generates higher-level strategic decisions
4. autonomous_loop incorporates these into its actions
5. All decisions are audited

Usage:
    from shopee_agent.decision_integration import DecisionIntegrator
    
    integrator = DecisionIntegrator(
        engine=decision_engine,
        store_id="my_store",
        metrics_dir="reports/"
    )
    
    # During autonomous_loop cycle:
    signals = integrator.collect_signals_from_metrics()
    context = integrator.build_economic_context()
    decisions = integrator.process_and_execute()
"""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.agent_orchestrator import AgentOrchestrator, ExecutionPlan
from shopee_agent.autonomous_strategy import AutonomousStrategyLayer, AutonomousStrategySnapshot
from shopee_agent.branding_growth import BrandingGrowthAnalyzer, BrandingGrowthSnapshot
from shopee_agent.competitive_intelligence import CompetitiveIntelligence, CompetitiveSnapshot
from shopee_agent.decision_engine import (
    Decision,
    DecisionEngine,
    DecisionPriority,
    DecisionSignal,
    DecisionStatus,
    DecisionType,
    EconomicContext,
)
from shopee_agent.economic_brain import EconomicBrain, EconomicBrainSnapshot
from shopee_agent.goal_management import GoalManager, PriorityEngine
from shopee_agent.paths import REPORTS_DIR, SECRETS_DIR
from shopee_agent.planner import PlanExecution, Planner
from shopee_agent.predictive_analytics import PredictiveAnalytics, PredictiveSnapshot
from shopee_agent.strategic_planner import GoalStack, PlanAssessment, PlanTimeline, StrategicPlan, StrategicPlanner
from shopee_agent.supply_chain_planner import SupplyChainPlan, SupplyChainPlanner

logger = logging.getLogger("laura.decision_integration")


class DecisionIntegrator:
    """
    Integrates Decision Engine with existing Laura components.
    
    Responsibilities:
    1. Transform operational data → decision signals
    2. Aggregate state → economic context
    3. Execute approved decisions through Laura modules
    4. Log outcomes for continuous learning
    """

    def __init__(
        self,
        engine: DecisionEngine,
        store_id: str,
        metrics_dir: str = str(REPORTS_DIR) + "/",
        log_interval_minutes: int = 15,
        agent_orchestrator: AgentOrchestrator | None = None,
        strategic_planner: StrategicPlanner | None = None,
        goal_stack: GoalStack | None = None,
        goal_manager: GoalManager | None = None,
        priority_engine: PriorityEngine | None = None,
        competitive_intelligence: CompetitiveIntelligence | None = None,
        branding_growth: BrandingGrowthAnalyzer | None = None,
        planner: Planner | None = None,
        economic_brain: EconomicBrain | None = None,
        predictive_analytics: PredictiveAnalytics | None = None,
        supply_chain_planner: SupplyChainPlanner | None = None,
        autonomous_strategy: AutonomousStrategyLayer | None = None,
    ):
        self.engine = engine
        self.store_id = store_id
        self.metrics_dir = Path(metrics_dir)
        self.log_interval_minutes = log_interval_minutes
        self.last_decision_cycle = None
        self.agent_orchestrator = agent_orchestrator
        self.last_orchestration_plan: ExecutionPlan | None = None
        self.strategic_planner = strategic_planner
        self.goal_stack = goal_stack or GoalStack()
        self.goal_manager = goal_manager or GoalManager.from_goal_stack(self.goal_stack)
        self.priority_engine = priority_engine or PriorityEngine()
        self.last_strategic_plan: StrategicPlan | None = None
        self.last_plan_timeline: PlanTimeline | None = None
        self.last_plan_assessment: PlanAssessment | None = None
        self.last_goal_snapshot: dict[str, Any] | None = None
        self.competitive_intelligence = competitive_intelligence
        self.last_competitive_snapshot: CompetitiveSnapshot | None = None
        self.branding_growth = branding_growth
        self.last_branding_growth_snapshot: BrandingGrowthSnapshot | None = None
        self.planner = planner
        self.last_planner_execution: PlanExecution | None = None
        self.economic_brain = economic_brain
        self.last_economic_brain_snapshot: EconomicBrainSnapshot | None = None
        self.predictive_analytics = predictive_analytics
        self.last_predictive_snapshot: PredictiveSnapshot | None = None
        self.supply_chain_planner = supply_chain_planner
        self.last_supply_chain_plan: SupplyChainPlan | None = None
        self.autonomous_strategy = autonomous_strategy
        self.last_strategy_snapshot: AutonomousStrategySnapshot | None = None

        logger.info(
            f"DecisionIntegrator initialized for store {store_id} "
            f"with {log_interval_minutes}min interval"
        )

    def collect_signals_from_metrics(self) -> list[DecisionSignal]:
        """
        Read Laura metrics and generate decision signals.
        
        Monitors:
        - laura_profitability_latest.json → margin anomalies
        - laura_metrics.jsonl → operational anomalies
        - laura_webhook_ready_audit.jsonl → order processing issues
        - laura_profitability_llm_baseline_latest.json → LLM analysis results
        
        Returns:
            List of DecisionSignal objects
        """
        signals = []

        # Check profitability metrics
        profitability_signals = self._extract_profitability_signals()
        signals.extend(profitability_signals)

        # Check operational metrics
        operational_signals = self._extract_operational_signals()
        signals.extend(operational_signals)

        # Check alerts
        alert_signals = self._extract_alert_signals()
        signals.extend(alert_signals)

        logger.info(f"Collected {len(signals)} decision signals")
        return signals

    def _extract_profitability_signals(self) -> list[DecisionSignal]:
        """Extract signals from profitability metrics."""
        signals = []

        try:
            # Read latest profitability state
            profitability_file = self.metrics_dir / "laura_profitability_latest.json"
            if profitability_file.exists():
                with open(profitability_file) as f:
                    profitability = json.load(f)

                # Detect margin anomalies
                current_margin = profitability.get("gross_margin_pct", 0)
                baseline_margin = profitability.get("baseline_margin_pct", current_margin)

                margin_delta = baseline_margin - current_margin
                if margin_delta > 5:  # Margin dropped >5%
                    signals.append(DecisionSignal(
                        source="metrics.profitability",
                        signal_type="anomaly",
                        data={
                            "metric": "margin_drop",
                            "baseline_margin": baseline_margin,
                            "current_margin": current_margin,
                            "delta": margin_delta,
                            "anomaly_severity": min(1.0, margin_delta / 10.0),  # 0-1
                        },
                        context={"source_file": "laura_profitability_latest.json"},
                    ))

                # Detect ROAS degradation
                current_roas = profitability.get("actual_roas", 0)
                baseline_roas = profitability.get("baseline_roas", current_roas)

                if baseline_roas > 0:
                    roas_delta_pct = (baseline_roas - current_roas) / baseline_roas
                    if roas_delta_pct > 0.2:  # ROAS degraded >20%
                        signals.append(DecisionSignal(
                            source="metrics.profitability",
                            signal_type="opportunity",
                            data={
                                "metric": "low_roas",
                                "baseline_roas": baseline_roas,
                                "current_roas": current_roas,
                                "degradation_pct": roas_delta_pct,
                                "anomaly_severity": min(1.0, roas_delta_pct),
                            },
                            context={"source_file": "laura_profitability_latest.json"},
                        ))

        except Exception as e:
            logger.warning(f"Error extracting profitability signals: {e}")

        return signals

    def _extract_operational_signals(self) -> list[DecisionSignal]:
        """Extract signals from operational metrics."""
        signals = []

        try:
            # Read metrics log
            metrics_file = self.metrics_dir / "laura_metrics.jsonl"
            if metrics_file.exists():
                with open(metrics_file) as f:
                    recent_metrics = [json.loads(line) for line in f.readlines()[-100:]]

                # Detect patterns
                for metric in recent_metrics:
                    # High error rate
                    if metric.get("error_count", 0) > metric.get("success_count", 1):
                        signals.append(DecisionSignal(
                            source="metrics.operational",
                            signal_type="risk",
                            data={
                                "metric": "high_error_rate",
                                "errors": metric.get("error_count"),
                                "successes": metric.get("success_count"),
                                "anomaly_severity": 0.8,
                            },
                        ))
                        break  # Report once

        except Exception as e:
            logger.warning(f"Error extracting operational signals: {e}")

        return signals

    def _extract_alert_signals(self) -> list[DecisionSignal]:
        """Extract signals from active alerts."""
        signals = []

        try:
            # Read webhook ready audit (proxy for pending issues)
            audit_file = self.metrics_dir / "laura_webhook_ready_audit.jsonl"
            if audit_file.exists():
                with open(audit_file) as f:
                    audit_entries = [json.loads(line) for line in f.readlines()[-50:]]

                # Count pending orders
                pending_count = sum(1 for e in audit_entries if not e.get("webhook_sent"))
                if pending_count > 10:  # Many pending orders
                    signals.append(DecisionSignal(
                        source="metrics.alerts",
                        signal_type="risk",
                        data={
                            "metric": "pending_orders_backlog",
                            "pending_count": pending_count,
                            "anomaly_severity": min(1.0, pending_count / 50),
                        },
                    ))

        except Exception as e:
            logger.warning(f"Error extracting alert signals: {e}")

        return signals

    def build_economic_context(self) -> EconomicContext:
        """
        Aggregate current economic state from Laura's monitoring.
        
        Sources:
        - laura_profitability_latest.json
        - laura_metrics_latest.json
        - laura_profitability_state.json
        
        Returns:
            EconomicContext with current operational state
        """
        # Defaults (safe values if data unavailable)
        context = EconomicContext(
            current_margin_pct=15.0,
            margin_target_pct=18.0,
            daily_revenue_usd=5000.0,
            cash_buffer_usd=50000.0,
            inventory_days_on_hand=15,
            stock_risk_level="normal",
            active_promotions=0,
            advertising_spend_daily_usd=500.0,
            advertising_roas=2.0,
            customer_satisfaction_score=80.0,
            recent_anomalies=[],
        )

        try:
            # Read profitability state
            profitability_file = self.metrics_dir / "laura_profitability_latest.json"
            if profitability_file.exists():
                with open(profitability_file) as f:
                    prof = json.load(f)
                    context.current_margin_pct = prof.get("gross_margin_pct", context.current_margin_pct)
                    context.daily_revenue_usd = prof.get("daily_revenue_usd", context.daily_revenue_usd)
                    context.advertising_roas = prof.get("actual_roas", context.advertising_roas)

        except Exception as e:
            logger.warning(f"Error building context from profitability: {e}")

        try:
            # Read operational state
            state_file = self.metrics_dir / "laura_profitability_state.json"
            if state_file.exists():
                with open(state_file) as f:
                    state = json.load(f)
                    context.cash_buffer_usd = state.get("cash_buffer_usd", context.cash_buffer_usd)
                    context.inventory_days_on_hand = state.get("inventory_doh", context.inventory_days_on_hand)
                    context.stock_risk_level = state.get("inventory_status", context.stock_risk_level)
                    context.active_promotions = state.get("active_promotions", context.active_promotions)

        except Exception as e:
            logger.warning(f"Error building context from state: {e}")

        # Extract recent anomalies from metrics
        try:
            metrics_file = self.metrics_dir / "laura_metrics.jsonl"
            if metrics_file.exists():
                with open(metrics_file) as f:
                    recent_metrics = [json.loads(line) for line in f.readlines()[-10:]]
                    for metric in recent_metrics:
                        if metric.get("status") == "anomaly":
                            context.recent_anomalies.append(metric.get("type", "unknown"))

        except Exception as e:
            logger.warning(f"Error extracting recent anomalies: {e}")

        logger.info(f"Economic context built: margin={context.current_margin_pct:.1f}%, "
                   f"roas={context.advertising_roas:.2f}")

        return context

    def process_cycle(self) -> dict[str, Any]:
        """
        Run a complete decision cycle.
        
        1. Collect signals from metrics
        2. Build economic context
        3. Process signals through engine
        4. Execute approved decisions
        5. Log results
        
        Returns:
            Cycle summary with decisions generated/executed
        """
        cycle_start = datetime.now(UTC)

        # Collect signals
        signals = self.collect_signals_from_metrics()

        # Build context
        context = self.build_economic_context()

        orchestration_plan = None
        if self.agent_orchestrator is not None:
            orchestration_plan = self.agent_orchestrator.coordinate_cycle_sync(context)
            self.last_orchestration_plan = orchestration_plan

        strategic_plan_data = None
        if self.strategic_planner is not None:
            strategic_plan_data = self.strategic_planner.create_and_assess(self.goal_stack, context)
            self.last_strategic_plan = strategic_plan_data.get("plan")
            self.last_plan_timeline = strategic_plan_data.get("timeline")
            self.last_plan_assessment = strategic_plan_data.get("assessment")

        planner_data = None
        if self.planner is not None:
            if self.last_strategic_plan is not None:
                tasks = self.planner.build_plan_from_strategic_plan(self.last_strategic_plan)
            else:
                top_goal = self.goal_stack.top_goal()
                tasks = self.planner.build_plan_from_goal(top_goal) if top_goal is not None else []

            if tasks:
                self.last_planner_execution = self.planner.execute(tasks, lambda task: {"task_id": task.task_id, "action": task.action})
                planner_data = self.last_planner_execution.to_dict()

        economic_brain_data = None
        if self.economic_brain is not None:
            self.last_economic_brain_snapshot = self.economic_brain.analyze()
            economic_brain_data = self.last_economic_brain_snapshot.to_dict()

        goal_snapshot = None
        if self.goal_manager is not None:
            goal_snapshot = self.goal_manager.snapshot(context=context, priority_engine=self.priority_engine)
            self.last_goal_snapshot = goal_snapshot

        competitive_data = None
        if self.competitive_intelligence is not None:
            self.last_competitive_snapshot = self.competitive_intelligence.snapshot(
                our_prices=self._load_our_price_snapshot(),
            )
            competitive_data = self.last_competitive_snapshot.to_dict()

        branding_growth_data = None
        if self.branding_growth is not None:
            self.last_branding_growth_snapshot = self.branding_growth.snapshot()
            branding_growth_data = self.last_branding_growth_snapshot.to_dict()

        predictive_data = None
        if self.predictive_analytics is not None:
            self.last_predictive_snapshot = self.predictive_analytics.forecast_overview()
            predictive_data = self.last_predictive_snapshot.to_dict()

        supply_chain_data = None
        if self.supply_chain_planner is not None:
            self.last_supply_chain_plan = self.supply_chain_planner.plan_supply_chain()
            supply_chain_data = self.last_supply_chain_plan.to_dict()

        strategy_data = None
        if self.autonomous_strategy is not None:
            self.last_strategy_snapshot = self.autonomous_strategy.evaluate(context=context)
            strategy_data = self.last_strategy_snapshot.to_dict()

        # GOAP planning for complex goals (alternative to DAG planner)
        goap_plan_data = None
        goap_decision_ids: list[str] = []
        all_decisions: list[Any] = []
        try:
            from shopee_agent.skills.loader import discover_and_register
            from shopee_agent.skills.orchestrator import SkillOrchestrator

            discover_and_register()

            top_goal = self.goal_stack.top_goal() if self.goal_stack else None
            strategic_goal = (
                self.last_strategic_plan.to_dict().get("goal", {})
                if self.last_strategic_plan
                else {}
            )

            if top_goal is not None or strategic_goal:
                current_state = {
                    "margin_pct": context.current_margin_pct,
                    "daily_revenue": context.daily_revenue_usd,
                    "cash_buffer": context.cash_buffer_usd,
                    "stock_risk": context.stock_risk_level,
                    "active_promos": context.active_promotions,
                    "orders_pending_ship": bool(context.daily_revenue_usd > 0),
                    "stock_checked": False,
                    "margin_protected": False,
                    "support_handled": False,
                }
                if strategic_goal:
                    goal_state = dict(strategic_goal)
                else:
                    goal_state = {
                        "margin_pct": context.margin_target_pct,
                        "daily_revenue": context.daily_revenue_usd * 1.1,
                        "orders_pending_ship": False,
                        "stock_checked": True,
                        "margin_protected": True,
                        "support_handled": True,
                    }
                orch = SkillOrchestrator(event_bus=getattr(self, "_event_bus", None))
                eval_result = orch.evaluate_state(current_state, goal_state, max_depth=6)
                goap_plan_data = eval_result
                if eval_result["status"] == "executed":
                    ok_count = sum(1 for r in eval_result.get("results", []) if r.get("ok"))
                    logger.info(f"GOAP plan executed: {ok_count}/{len(eval_result.get('skills', []))} ok")
                    # Create Decision objects for engine audit trail
                    sig = DecisionSignal(source="goap", signal_type="routine", data=eval_result)
                    for i, r in enumerate(eval_result.get("results", [])):
                        did = f"goap_{r.get('skill', 'unknown')}_{cycle_start.strftime('%H%M%S')}_{i}"
                        d = Decision(
                            decision_id=did,
                            title=f"GOAP: {r.get('skill', 'unknown')}",
                            decision_type=DecisionType.ALERTS,
                            recommended_action=r.get("result", ""),
                            priority=DecisionPriority.LOW,
                            impact_score=1.0 if r.get("ok") else -0.5,
                            risk_score=0.3,
                            confidence_score=0.8,
                            status=DecisionStatus.APPROVED if r.get("ok") else DecisionStatus.FAILED,
                            signal=sig,
                            rule_id="goap_orchestrator",
                            description=r.get("skill", ""),
                            metadata={"skill": r.get("skill"), "goap": True},
                            created_at=cycle_start,
                        )
                        all_decisions.append(d)
                        self.engine.pending_decisions[d.decision_id] = d
                        goap_decision_ids.append(did)
        except Exception as exc:
            logger.warning(f"GOAP planning failed: {exc}")

        # Process through engine
        for signal in signals:
            decisions = self.engine.process_signal(signal, context)
            all_decisions.extend(decisions)

        # Summarize
        approved = [d for d in all_decisions if d.status == DecisionStatus.APPROVED]
        rejected = [d for d in all_decisions if d.status == DecisionStatus.REJECTED]

        logger.info(
            f"Decision cycle complete: {len(all_decisions)} decisions, "
            f"{len(approved)} approved, {len(rejected)} rejected"
        )

        self.last_decision_cycle = {
            "timestamp": cycle_start.isoformat(),
            "signals_received": len(signals),
            "decisions_generated": len(all_decisions),
            "decisions_approved": len(approved),
            "decisions_rejected": len(rejected),
            "critical_decisions": len([d for d in approved if d.priority == DecisionPriority.CRITICAL]),
            "orchestration": orchestration_plan.to_dict() if orchestration_plan else None,
            "goal_management": goal_snapshot,
            "competitive_intelligence": competitive_data,
            "branding_growth": branding_growth_data,
            "planner": planner_data,
            "economic_brain": economic_brain_data,
            "strategic_plan": {
                "plan": self.last_strategic_plan.to_dict() if self.last_strategic_plan else None,
                "timeline": self.last_plan_timeline.to_dict() if self.last_plan_timeline else None,
                "assessment": self.last_plan_assessment.to_dict() if self.last_plan_assessment else None,
            } if strategic_plan_data else None,
            "predictive_analytics": predictive_data,
            "supply_chain": supply_chain_data,
            "autonomous_strategy": strategy_data,
            "goap_plan": goap_plan_data,
        }

        return self.last_decision_cycle

    def get_pending_actions(
        self,
        decision_type: DecisionType | None = None,
        min_priority: DecisionPriority | None = None,
    ) -> list[Decision]:
        """
        Get pending decisions ready for autonomous_loop to execute.
        
        Used by autonomous_loop to retrieve high-priority decisions.
        """
        return self.engine.get_pending_decisions(
            decision_type=decision_type,
            min_priority=min_priority,
        )

    def mark_decision_executed(self, decision_id: str) -> bool:
        """Called by autonomous_loop after executing a decision."""
        return self.engine.execute_decision(decision_id)

    def _load_our_price_snapshot(self) -> dict[str, float]:
        snapshot_path = self.metrics_dir / "product_prices.json"
        if not snapshot_path.exists():
            return {}

        try:
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(raw, dict):
            return {}

        prices: dict[str, float] = {}
        for item_id, value in raw.items():
            try:
                prices[str(item_id)] = float(value)
            except Exception:
                continue
        return prices


class DecisionExecutor:
    """
    Executes decisions through Shopee API.
    
    Bridges:
    - PRICING decisions → shopee_client.update_item_price()
    - ADS decisions → shopee_client.update_campaign() / update_ad_group()
    - INVENTORY decisions → shopee_client.update_item_stock()
    - ALERTS decisions → Telegram / logger dispatch
    """

    def __init__(
        self,
        store_id: str,
        autopilot_config_path: str = str(SECRETS_DIR) + "/",
        engine: DecisionEngine | None = None,
        client: Any | None = None,
    ):
        self.store_id = store_id
        self.autopilot_config_path = Path(autopilot_config_path)
        self.engine = engine
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from shopee_agent.client import ShopeeClient
            from shopee_agent.config import load_config
            cfg = load_config()
            self._client = ShopeeClient(cfg)
        return self._client

    def _get_tokens(self) -> tuple[str, int]:
        cfg = None
        try:
            from shopee_agent.config import load_config
            cfg = load_config()
        except Exception:
            pass
        if cfg is None:
            from shopee_agent.config import load_config
            cfg = load_config()
        shop_id = cfg.default_shop_id or 0
        token = cfg.default_access_token or ""
        return token, shop_id

    def execute(self, decision: Decision) -> bool:
        logger.info(f"Executing decision {decision.decision_id}: {decision.title}")

        md = decision.metadata if isinstance(decision.metadata, dict) else {}
        skill_name = md.get("skill") or md.get("skill_name")
        if skill_name:
            result = self.execute_skill_action(skill_name, context=md)
            if result is None:
                logger.warning(f"Skill '{skill_name}' not found, falling back to type dispatch")
            else:
                success = result
                if success and self.engine is not None:
                    try:
                        self.engine.execute_decision(decision.decision_id)
                    except Exception:
                        logger.exception("Failed to notify engine of executed decision")
                return success

        if decision.decision_type == DecisionType.PRICING:
            success = self._execute_pricing_decision(decision)
        elif decision.decision_type == DecisionType.ADS:
            success = self._execute_ads_decision(decision)
        elif decision.decision_type == DecisionType.INVENTORY:
            success = self._execute_inventory_decision(decision)
        elif decision.decision_type == DecisionType.ALERTS:
            success = self._execute_alerts_decision(decision)
        else:
            logger.warning(f"No executor for decision type {decision.decision_type}")
            return False

        if success and self.engine is not None:
            try:
                self.engine.execute_decision(decision.decision_id)
            except Exception:
                logger.exception("Failed to notify engine of executed decision")

        return success

    def _execute_pricing_decision(self, decision: Decision) -> bool:
        md = decision.metadata if isinstance(decision.metadata, dict) else {}
        item_id = md.get("item_id")
        current_price = md.get("current_price")
        variation_id = md.get("variation_id")
        if not item_id or current_price is None:
            logger.warning(f"[PRICING] Missing item_id or current_price in metadata: {md}")
            return False
        try:
            client = self._get_client()
            token, shop_id = self._get_tokens()
            resp = client.update_item_price(
                access_token=token,
                shop_id=shop_id,
                item_id=int(item_id),
                current_price=float(current_price),
                variation_id=int(variation_id) if variation_id else None,
            )
            if resp.error:
                logger.error(f"[PRICING] API error for item {item_id}: {resp.error}")
                return False
            logger.info(f"[PRICING] Price updated for item {item_id}: {current_price}")
            return True
        except Exception:
            logger.exception(f"[PRICING] Failed to update price for item {item_id}")
            return False

    def _execute_ads_decision(self, decision: Decision) -> bool:
        md = decision.metadata if isinstance(decision.metadata, dict) else {}
        campaign_id = md.get("campaign_id")
        ad_group_id = md.get("ad_group_id")
        updates = md.get("updates", {})
        if not updates:
            logger.warning(f"[ADS] No updates provided in metadata: {md}")
            return False
        try:
            client = self._get_client()
            token, shop_id = self._get_tokens()
            if campaign_id:
                resp = client.update_campaign(
                    access_token=token,
                    shop_id=shop_id,
                    campaign_id=int(campaign_id),
                    updates=updates,
                )
                if resp.error:
                    logger.error(f"[ADS] API error for campaign {campaign_id}: {resp.error}")
                    return False
                logger.info(f"[ADS] Campaign {campaign_id} updated: {updates}")
            elif ad_group_id:
                resp = client.update_ad_group(
                    access_token=token,
                    shop_id=shop_id,
                    ad_group_id=int(ad_group_id),
                    updates=updates,
                )
                if resp.error:
                    logger.error(f"[ADS] API error for ad_group {ad_group_id}: {resp.error}")
                    return False
                logger.info(f"[ADS] Ad group {ad_group_id} updated: {updates}")
            else:
                logger.warning("[ADS] Neither campaign_id nor ad_group_id in metadata")
                return False
            return True
        except Exception:
            logger.exception("[ADS] Failed to update ad")
            return False

    def _execute_inventory_decision(self, decision: Decision) -> bool:
        md = decision.metadata if isinstance(decision.metadata, dict) else {}
        item_id = md.get("item_id")
        stock = md.get("stock")
        variation_id = md.get("variation_id")
        if not item_id or stock is None:
            logger.warning(f"[INVENTORY] Missing item_id or stock in metadata: {md}")
            return False
        try:
            client = self._get_client()
            token, shop_id = self._get_tokens()
            resp = client.update_item_stock(
                access_token=token,
                shop_id=shop_id,
                item_id=int(item_id),
                stock=int(stock),
                variation_id=int(variation_id) if variation_id else None,
            )
            if resp.error:
                logger.error(f"[INVENTORY] API error for item {item_id}: {resp.error}")
                return False
            logger.info(f"[INVENTORY] Stock updated for item {item_id}: {stock}")
            return True
        except Exception:
            logger.exception(f"[INVENTORY] Failed to update stock for item {item_id}")
            return False

    def _execute_alerts_decision(self, decision: Decision) -> bool:
        try:
            msg = f"[LAURA ALERT] {decision.title}: {decision.recommended_action}"
            logger.warning(msg)
            telegram_chat_id = os.getenv("LAURA_ALERT_TELEGRAM_CHAT_ID", "")
            telegram_token = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "")
            if telegram_chat_id and telegram_token:
                import requests as _req
                url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                _req.post(url, json={"chat_id": telegram_chat_id, "text": msg}, timeout=10)
            return True
        except Exception:
            logger.exception("[ALERTS] Failed to dispatch alert")
            return False

    def execute_skill_action(self, skill_name: str, **kwargs: Any) -> bool | None:
        """Execute a registered skill by name, returns True on success."""
        import asyncio

        from shopee_agent.skills.registry import default_registry, invoke

        cls = default_registry.get(skill_name)
        if cls is None:
            logger.warning(f"Skill '{skill_name}' not found in registry")
            return None
        try:
            skill = cls(client=self._client)
            result = asyncio.run(invoke(skill, **kwargs))
            logger.info(f"Skill '{skill_name}' executed: {str(result)[:200]}")
            return True
        except Exception as e:
            logger.exception(f"Skill '{skill_name}' failed: {e}")
            return False

    def execute_goap_plan(self, plan: list[Any], context: Any = None) -> list[bool | None]:
        """Execute a GOAP plan (list of GOAPAction)."""
        results = []
        for action in plan:
            action_name = getattr(action, "name", str(action))
            skill_kwargs = {"context": context} if context else {}
            result = self.execute_skill_action(action_name, **skill_kwargs)
            results.append(result)
            if result is False:
                logger.warning(f"GOAP plan aborted at action '{action_name}'")
                break
        return results
