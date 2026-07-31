"""
Adaptive Decision Rules & Feedback Loop (Phase 35 - Memory & Learning Layer)

Extends the Decision Engine with:
1. AdaptiveRule / AdaptiveRuleEngine — self-tuning rules that adjust weights
   based on outcome history, evaluated via restricted eval()
2. FeedbackLoop — processes execution outcomes, runs periodic adaptation
   cycles (adjust weights → detect patterns → suggest new rules → prune)
3. AdaptiveIntegrator — wraps DecisionIntegrator so every decision cycle
   also runs adaptive rule evaluation and feeds results back into learning

Design:
- All learning logic uses stdlib only (no external ML libraries).
- Rule condition/action are Python expressions evaluated with a restricted
  globals dict (safe builtins + primitive context values only).
- Persistence is JSON-based under reports/ for transparency and debuggability.
"""

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.decision_engine import DecisionEngine, DecisionStatus
from shopee_agent.decision_integration import DecisionIntegrator
from shopee_agent.decision_memory import DecisionOutcome, MemoryLayer

logger = logging.getLogger("laura.decision_adaptive")

# ---------------------------------------------------------------------------
# Safe restricted globals for eval() — no I/O, no imports, no side effects
# ---------------------------------------------------------------------------
_SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}


@dataclass
class AdaptiveRule:
    """A single adaptive rule with learned weight and outcome counters."""
    rule_id: str
    condition: str
    action: str
    weight: float = 1.0
    success_count: int = 0
    failure_count: int = 0
    last_outcome: str | None = None
    last_updated: str = ""


class AdaptiveRuleEngine:
    """Manages a collection of AdaptiveRules, evaluates them against a context
    dict, records outcomes, and can self-adjust weights and suggest new rules."""

    def __init__(self, rules_path: str = "reports/rules_state.json"):
        self.rules_path = Path(rules_path)
        self._rules: dict[str, AdaptiveRule] = {}
        self._evaluation_log: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.rules_path.exists():
            return
        try:
            with open(self.rules_path) as f:
                data = json.load(f)
            for item in data.get("rules", []):
                self._rules[item["rule_id"]] = AdaptiveRule(**item)
            self._evaluation_log = data.get("evaluation_log", [])
            logger.info("Loaded %d adaptive rules from %s", len(self._rules), self.rules_path)
        except Exception as exc:
            logger.warning("Failed to load adaptive rules: %s", exc)

    def _save(self) -> None:
        try:
            self.rules_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "rules": [asdict(r) for r in self._rules.values()],
                "evaluation_log": self._evaluation_log[-2000:],
                "updated_at": datetime.now(UTC).isoformat(),
            }
            with open(self.rules_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to save adaptive rules: %s", exc)

    # ------------------------------------------------------------------
    # Safe expression evaluation
    # ------------------------------------------------------------------
    @staticmethod
    def _eval_safe(expr: str, context: dict) -> Any:
        """Evaluate a Python expression with a restricted globals dict.

        Only primitive types (str, int, float, bool, list, dict, tuple, None)
        from *context* are injected, preventing arbitrary object access.
        """
        allowed: dict = dict(_SAFE_BUILTINS)
        for k, v in context.items():
            if isinstance(v, (str, int, float, bool, list, dict, tuple, type(None))):
                allowed[k] = v
        return eval(expr, {"__builtins__": {}}, allowed)

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------
    def add_rule(self, rule: AdaptiveRule) -> bool:
        if rule.rule_id in self._rules:
            logger.warning("Adaptive rule '%s' already exists — rejected", rule.rule_id)
            return False
        rule.last_updated = datetime.now(UTC).isoformat()
        self._rules[rule.rule_id] = rule
        self._save()
        logger.info("Adaptive rule added: %s  (condition=%s)", rule.rule_id, rule.condition)
        return True

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id not in self._rules:
            return False
        del self._rules[rule_id]
        self._save()
        return True

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def evaluate(self, context: dict) -> list[dict]:
        """Evaluate all active (weight >= 0.01) rules against *context*.

        Returns a list of result dicts, one per matched rule:
            {"rule_id", "condition", "action", "weight", "result"}
        """
        results: list[dict] = []
        for rule in list(self._rules.values()):
            if rule.weight < 0.01:
                continue
            try:
                cond_result = self._eval_safe(rule.condition, context)
                if cond_result:
                    action_result = self._eval_safe(rule.action, context)
                    results.append({
                        "rule_id": rule.rule_id,
                        "condition": rule.condition,
                        "action": rule.action,
                        "weight": rule.weight,
                        "result": action_result,
                    })
            except Exception as exc:
                logger.debug("Adaptive rule '%s' eval error: %s", rule.rule_id, exc)

        self._evaluation_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "context_keys": list(context.keys()),
            "matched_rules": len(results),
            "total_active": len(self._rules),
        })
        return results

    # ------------------------------------------------------------------
    # Outcome recording & weight adjustment
    # ------------------------------------------------------------------
    def record_outcome(self, rule_id: str, success: bool, impact: float = 0.0) -> None:
        if rule_id not in self._rules:
            return
        rule = self._rules[rule_id]
        if success:
            rule.success_count += 1
            rule.last_outcome = "success"
        else:
            rule.failure_count += 1
            rule.last_outcome = "failure"

        rule.last_updated = datetime.now(UTC).isoformat()

        if impact != 0.0:
            clip = max(-0.2, min(0.2, impact))
            rule.weight = max(0.01, min(5.0, rule.weight + clip))

        self._save()

    def adjust_weights(self) -> None:
        """Sweep all rules and nudge weight based on historical success rate.

        High-success rules (rate > 0.7) get a small boost.
        Low-success rules (rate < 0.3) get a small penalty.
        Rules with fewer than 3 total outcomes are left unchanged.
        """
        for rule in self._rules.values():
            total = rule.success_count + rule.failure_count
            if total < 3:
                continue
            rate = rule.success_count / total
            if rate > 0.7:
                rule.weight = min(5.0, rule.weight * 1.1)
            elif rate < 0.3:
                rule.weight = max(0.01, rule.weight * 0.85)
            else:
                rule.weight = rule.weight * 0.95 + 1.0 * 0.05
            rule.last_updated = datetime.now(UTC).isoformat()
        self._save()

    # ------------------------------------------------------------------
    # Statistics & suggestions
    # ------------------------------------------------------------------
    def get_stats(self) -> dict:
        total = len(self._rules)
        if total == 0:
            return {
                "total_rules": 0,
                "active_rules": 0,
                "avg_weight": 0.0,
                "total_successes": 0,
                "total_failures": 0,
                "overall_success_rate": 0.0,
                "total_evaluations": len(self._evaluation_log),
            }

        active = sum(1 for r in self._rules.values() if r.weight >= 0.01)
        avg_w = sum(r.weight for r in self._rules.values()) / total
        succ = sum(r.success_count for r in self._rules.values())
        fail = sum(r.failure_count for r in self._rules.values())

        return {
            "total_rules": total,
            "active_rules": active,
            "avg_weight": round(avg_w, 4),
            "min_weight": round(min(r.weight for r in self._rules.values()), 4),
            "max_weight": round(max(r.weight for r in self._rules.values()), 4),
            "total_successes": succ,
            "total_failures": fail,
            "overall_success_rate": round(succ / (succ + fail), 4) if succ + fail > 0 else 0.0,
            "total_evaluations": len(self._evaluation_log),
        }

    def suggest_new_rules(self, patterns: list[dict]) -> list[AdaptiveRule]:
        """Generate candidate AdaptiveRules from detected pattern dicts.

        Each *pattern* should have keys:
            condition (str), action (str), name (str), initial_weight (float)

        Duplicate conditions (normalised) are skipped.
        """
        suggestions: list[AdaptiveRule] = []
        seen_conditions = {r.condition.strip() for r in self._rules.values()}
        seen_ids = set(self._rules.keys())

        for i, pat in enumerate(patterns):
            cond = pat.get("condition", "")
            act = pat.get("action", "")
            if not cond or not act:
                continue
            if cond.strip() in seen_conditions:
                continue

            base = pat.get("name", f"pattern_{i}")
            rid = f"adauto_{base}_{uuid.uuid4().hex[:6]}"
            while rid in seen_ids:
                rid = f"adauto_{base}_{uuid.uuid4().hex[:6]}"
            seen_ids.add(rid)
            seen_conditions.add(cond.strip())

            suggestions.append(AdaptiveRule(
                rule_id=rid,
                condition=cond,
                action=act,
                weight=float(pat.get("initial_weight", 0.5)),
            ))
        return suggestions

    def count(self) -> int:
        return len(self._rules)


class FeedbackLoop:
    """Connects adaptive rules to execution outcomes.

    Periodically:
    1. Reads recent DecisionOutcomes from MemoryLayer
    2. Aggregates outcome statistics per rule_id
    3. Records success/failure on the AdaptiveRuleEngine
    4. Adjusts weights
    5. Detects metric/pattern signals for new rule suggestions
    6. Prunes persistently low-performing rules
    7. Maintains a learning curve for monitoring
    """

    def __init__(self, engine: AdaptiveRuleEngine, memory: MemoryLayer):
        self.engine = engine
        self.memory = memory
        self._learning_curve: list[dict] = []
        self._cycle_count = 0
        self._load_curve()

    # ------------------------------------------------------------------
    # Persistence for learning curve
    # ------------------------------------------------------------------
    def _load_curve(self) -> None:
        p = Path("reports/adaptive_learning_curve.json")
        if p.exists():
            try:
                with open(p) as f:
                    self._learning_curve = json.load(f)
            except Exception:
                pass

    def _save_curve(self) -> None:
        p = Path("reports/adaptive_learning_curve.json")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w") as f:
                json.dump(self._learning_curve[-1000:], f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Outcome processing
    # ------------------------------------------------------------------
    def process_outcome(self, decision_id: str, outcome: dict) -> None:
        route_id = outcome.get("rule_id", "")
        if not route_id:
            return
        success = bool(outcome.get("success", False))
        impact = float(outcome.get("impact", 0.0))
        self.engine.record_outcome(route_id, success, impact)

    # ------------------------------------------------------------------
    # Full adaptation cycle
    # ------------------------------------------------------------------
    def run_adaptation_cycle(self) -> dict:
        self._cycle_count += 1
        recent = self.memory.list_outcomes(limit=500)

        # Aggregate per rule
        by_rule: dict[str, list] = defaultdict(list)
        for o in recent:
            by_rule[o.rule_id].append(o)

        for rule_id, outcomes in by_rule.items():
            if len(outcomes) < 3:
                continue
            successes = sum(1 for o in outcomes if o.outcome_type == "success")
            partials = sum(1 for o in outcomes if o.outcome_type == "partial")
            failures = sum(1 for o in outcomes if o.outcome_type in ("failure", "reverted"))
            effective = successes + partials * 0.5
            total = effective + failures
            if total == 0:
                continue
            rate = effective / total
            avg_impact = sum(o.impact_realized or 0.0 for o in outcomes) / len(outcomes)
            self.engine.record_outcome(rule_id, rate > 0.5, avg_impact)

        self.engine.adjust_weights()

        patterns = self._detect_patterns(recent)
        new_rules = self.engine.suggest_new_rules(patterns)
        pruned = self._prune_low_performers()

        stats = self.engine.get_stats()
        pt = {
            "cycle": self._cycle_count,
            "timestamp": datetime.now(UTC).isoformat(),
            "total_rules": stats["total_rules"],
            "active_rules": stats["active_rules"],
            "avg_weight": stats["avg_weight"],
            "overall_success_rate": stats["overall_success_rate"],
            "new_rules_suggested": len(new_rules),
            "pruned_rules": pruned,
            "outcomes_analyzed": len(recent),
        }
        self._learning_curve.append(pt)
        self._save_curve()

        return {
            "cycle": self._cycle_count,
            "timestamp": pt["timestamp"],
            "outcomes_analyzed": len(recent),
            "new_rules_suggested": [asdict(r) for r in new_rules],
            "pruned_rules": pruned,
            "engine_stats": stats,
            "curve_point": pt,
        }

    # ------------------------------------------------------------------
    # Pattern detection (stdlib only — basic co-occurrence heuristics)
    # ------------------------------------------------------------------
    def _detect_patterns(self, outcomes: list[DecisionOutcome]) -> list[dict]:
        patterns: list[dict] = []

        if len(outcomes) < 5:
            return patterns

        # 1.  Per-rule split suggestions for rules with mixed (40‑60 %) results
        by_rule: dict[str, list] = defaultdict(list)
        for o in outcomes:
            by_rule[o.rule_id].append(o)

        for rule_id, outs in by_rule.items():
            if len(outs) < 10:
                continue
            successes = sum(1 for o in outs if o.outcome_type == "success")
            rate = successes / len(outs)
            if 0.35 <= rate <= 0.65:
                patterns.append({
                    "condition": 'context.get("margin_pct", 0) > 18',
                    "action": f'{{"action": "tighten_rule", "target": "{rule_id}"}}',
                    "name": f"tighten_{rule_id}",
                    "initial_weight": 0.3,
                })

        # 2.  High-impact clusters
        high_impact = [o for o in outcomes if o.impact_realized is not None and abs(o.impact_realized) > 0.08]
        if len(high_impact) >= 3:
            pos = sum(1 for o in high_impact if o.impact_realized > 0)
            neg = len(high_impact) - pos
            if pos > neg * 2:
                patterns.append({
                    "condition": 'context.get("cash_buffer", 0) > 5000',
                    "action": '{"action": "aggressive_optimization", "confidence": 0.7}',
                    "name": "high_impact_positive",
                    "initial_weight": 0.6,
                })
            elif neg > pos * 2:
                patterns.append({
                    "condition": 'context.get("stock_risk", "normal") == "critical"',
                    "action": '{"action": "conservative_mode", "confidence": 0.9}',
                    "name": "high_impact_negative",
                    "initial_weight": 0.7,
                })

        return patterns

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------
    def _prune_low_performers(self) -> int:
        to_remove: list[str] = []
        for rid, rule in self.engine._rules.items():
            total = rule.success_count + rule.failure_count
            if total < 5:
                continue
            if rule.weight < 0.05 and rule.failure_count / total > 0.8:
                to_remove.append(rid)

        for rid in to_remove:
            self.engine.remove_rule(rid)
        if to_remove:
            logger.info("Pruned %d low-performing adaptive rules: %s", len(to_remove), to_remove)
        return len(to_remove)

    # ------------------------------------------------------------------
    # Learning curve
    # ------------------------------------------------------------------
    def get_learning_curve(self) -> list[dict]:
        return list(self._learning_curve)


class AdaptiveIntegrator:
    """Wraps a DecisionIntegrator with the adaptive rule layer.

    After each decision cycle:
    1. Evaluates all AdaptiveRules against the current economic context
    2. Records outcomes for every executed decision via FeedbackLoop
    3. Runs a full adaptation cycle (adjust → suggest → prune)
    4. Optionally auto-adds high-confidence suggested rules
    """

    def __init__(
        self,
        integrator: DecisionIntegrator,
        adaptive_engine: AdaptiveRuleEngine,
        memory: MemoryLayer,
        auto_add_suggestions: bool = True,
    ):
        self._integrator = integrator
        self._adaptive = adaptive_engine
        self._memory = memory
        self._feedback = FeedbackLoop(adaptive_engine, memory)
        self._auto_add_suggestions = auto_add_suggestions
        self._cycle_count = 0
        self._rule_performance: dict[str, list[dict]] = defaultdict(list)

    # Expose the underlying engine for convenience
    @property
    def engine(self) -> DecisionEngine:
        return self._integrator.engine

    @property
    def feedback(self) -> FeedbackLoop:
        return self._feedback

    # Delegate standard methods
    def collect_signals_from_metrics(self):
        return self._integrator.collect_signals_from_metrics()

    def build_economic_context(self):
        return self._integrator.build_economic_context()

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------
    def process_cycle(self) -> dict:
        self._cycle_count += 1

        # 1. Standard decision cycle
        base_result = self._integrator.process_cycle()

        # 2. Build lightweight context dict for adaptive rules
        ctx = self._integrator.build_economic_context()
        context_dict = {
            "margin_pct": ctx.current_margin_pct,
            "margin_target": ctx.margin_target_pct,
            "daily_revenue": ctx.daily_revenue_usd,
            "cash_buffer": ctx.cash_buffer_usd,
            "stock_risk": ctx.stock_risk_level,
            "active_promos": ctx.active_promotions,
            "ad_spend": ctx.advertising_spend_daily_usd,
            "roas": ctx.advertising_roas,
            "csat": ctx.customer_satisfaction_score,
            "anomaly_count": len(ctx.recent_anomalies),
        }

        # 3. Evaluate adaptive rules
        adaptive_results = self._adaptive.evaluate(context_dict)

        # 4. Track matched adaptive rules
        for match in adaptive_results:
            rid = match["rule_id"]
            self._rule_performance[rid].append({
                "cycle": self._cycle_count,
                "timestamp": datetime.now(UTC).isoformat(),
                "action": match.get("result"),
                "context_snapshot": context_dict,
            })
            logger.info("Adaptive rule '%s' fired — action=%s", rid, match.get("result"))

        # 5. Feed back outcomes from executed decisions this cycle
        executed = [
            d for d in self._integrator.engine.pending_decisions.values()
            if d.status == DecisionStatus.EXECUTED
        ]
        for dec in executed:
            candidates = [o for o in self._memory.list_outcomes(limit=100) if o.decision_id == dec.decision_id]
            if candidates:
                latest = candidates[-1]
                ok = latest.outcome_type in ("success", "partial")
                self._feedback.process_outcome(
                    dec.decision_id,
                    {"rule_id": dec.rule_id, "success": ok, "impact": latest.impact_realized or 0.0},
                )

        # 6. Run full adaptation cycle
        adaptation_result = self._feedback.run_adaptation_cycle()

        # 7. Auto-add promising suggestions
        auto_added = 0
        if self._auto_add_suggestions:
            for sd in adaptation_result.get("new_rules_suggested", []):
                r = AdaptiveRule(**sd)
                if r.weight >= 0.4 and self._adaptive.add_rule(r):
                    auto_added += 1

        self._rule_performance["_meta"].append({
            "cycle": self._cycle_count,
            "timestamp": datetime.now(UTC).isoformat(),
            "adaptive_matches": len(adaptive_results),
            "auto_added_rules": auto_added,
        })

        # 8. Merge results
        merged: dict = {
            **base_result,
            "adaptive": {
                "rules_total": self._adaptive.count(),
                "rules_matched": len(adaptive_results),
                "adaptation": adaptation_result,
                "auto_added_rules": auto_added,
            },
        }
        return merged

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def get_adaptive_summary(self) -> dict:
        return {
            "adaptive_rules": self._adaptive.get_stats(),
            "learning_curve_points": len(self._feedback.get_learning_curve()),
            "cycle_count": self._cycle_count,
            "auto_add_suggestions": self._auto_add_suggestions,
            "tracked_rules": len(self._rule_performance),
        }
