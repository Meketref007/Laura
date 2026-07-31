"""GOAP (Goal-Oriented Action Planning) for Laura.

Uses A* search to find sequences of actions that achieve current goals.
Supports learning: action costs auto-adjust based on outcome history.
Includes plan cache, multi-agent support, and budget-aware planning.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shopee_agent.logger import info
from shopee_agent.paths import GOAP_LEARNING

try:
    from shopee_agent.plan_store import PlanStore
except ImportError:
    PlanStore = None  # type: ignore


@dataclass
class GOAPAction:
    name: str
    cost: float = 1.0
    preconditions: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # higher = executed first regardless of cost
    reverse_name: str = ""  # skill name for compensation/rollback
    sub_skills: list[str] = field(default_factory=list)  # composed sub-skills
    version: str = ""  # used for A/B testing (e.g. "v1", "v2")

    def is_valid(self, state: dict[str, Any]) -> bool:
        for k, v in self.preconditions.items():
            if k.startswith("__op__"):
                continue  # internal key
            if k.startswith("gt_"):
                actual = state.get(k[3:])
                if not (actual is not None and actual > v):
                    return False
            elif k.startswith("gte_"):
                actual = state.get(k[4:])
                if not (actual is not None and actual >= v):
                    return False
            elif k.startswith("lt_"):
                actual = state.get(k[3:])
                if not (actual is not None and actual < v):
                    return False
            elif k.startswith("lte_"):
                actual = state.get(k[4:])
                if not (actual is not None and actual <= v):
                    return False
            elif k.startswith("ne_"):
                actual = state.get(k[3:])
                if not (actual is not None and actual != v):
                    return False
            elif k.startswith("in_"):
                actual = state.get(k[3:])
                if not (actual is not None and actual in (v if isinstance(v, (list, tuple, set)) else [v])):
                    return False
            else:
                if state.get(k) != v:
                    return False
        return True

    def apply_effects(self, state: dict[str, Any]) -> dict[str, Any]:
        new_state = dict(state)
        new_state.update(self.effects)
        return new_state

    def inverse_effects(self, state: dict[str, Any]) -> dict[str, Any]:
        new_state = dict(state)
        for k in self.effects:
            new_state.pop(k, None)
        return new_state

    def conflicts_with(self, other: GOAPAction) -> bool:
        self_keys = set(self.effects)
        other_keys = set(other.effects)
        return bool(self_keys & other_keys)


@dataclass
class GOAPNode:
    state: dict[str, Any]
    actions: list[GOAPAction] = field(default_factory=list)
    cost: float = 0.0
    heuristic: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.cost + self.heuristic

    def __lt__(self, other: GOAPNode) -> bool:
        return self.total_cost < other.total_cost


def _default_heuristic(state: dict[str, Any], goal: dict[str, Any]) -> float:
    return float(sum(1 for k, v in goal.items() if state.get(k) != v))


def _state_hash(state: dict[str, Any]) -> str:
    raw = json.dumps(state, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode()).hexdigest()


class GOAPPlanner:
    """A* planner with adaptive cost learning, plan cache, and budget support."""

    def __init__(self, learning_path: str = str(GOAP_LEARNING), use_sqlite: bool = True):
        self._actions: list[GOAPAction] = []
        self._skill_registry: Any | None = None
        self._learning_path = Path(learning_path)
        self._learning_path.parent.mkdir(parents=True, exist_ok=True)
        self._cost_overrides: dict[str, float] = {}
        self._plan_cache: dict[str, list[GOAPAction]] = {}
        self._use_sqlite = use_sqlite
        self._learning_db: Any | None = None
        if use_sqlite:
            from shopee_agent.learning_db import LearningDB
            db_path = str(self._learning_path.with_suffix(".db"))
            self._learning_db = LearningDB(db_path=db_path)
        self._load_learning()

    def load_skills(self, registry: Any) -> None:
        self._skill_registry = registry
        for name in registry.list():
            skill_cls = registry.get(name)
            if skill_cls is None:
                continue
            pre = dict(getattr(skill_cls, "preconditions", {}))
            eff = dict(getattr(skill_cls, "effects", {}))
            base_cost = float(getattr(skill_cls, "cost", 1.0))
            prio = int(getattr(skill_cls, "priority", 0))
            rev = str(getattr(skill_cls, "reverse_name", ""))
            subs = list(getattr(skill_cls, "sub_skills", []))
            ver = str(getattr(skill_cls, "version", ""))
            if self._learning_db:
                learned = self._learning_db.get_cost(name, default=base_cost)
            else:
                learned = self._cost_overrides.get(name, base_cost)
            action = GOAPAction(
                name=name,
                cost=learned,
                preconditions=pre,
                effects=eff,
                priority=prio,
                reverse_name=rev,
                sub_skills=subs,
                version=ver,
            )
            self._actions.append(action)

    def register_action(self, action: GOAPAction) -> None:
        self._actions.append(action)

    def clear_cache(self) -> None:
        self._plan_cache.clear()

    def plan(
        self,
        start_state: dict[str, Any],
        goal: dict[str, Any],
        max_depth: int = 10,
        use_cache: bool = True,
        max_budget: float | None = None,
    ) -> list[GOAPAction] | None:
        """A* search from start_state to goal.

        If max_budget is set, prunes branches whose cost exceeds the budget.
        """
        if use_cache:
            cache_key = (_state_hash(start_state) + "|" + _state_hash(goal) + "|" + str(max_depth) + "|" + str(max_budget))
            cached = self._plan_cache.get(cache_key)
            if cached is not None:
                info(f"GOAP: returning cached plan ({len(cached)} actions)")
                return cached

        sorted_actions = sorted(self._actions, key=lambda a: (-a.priority, a.cost))
        start_node = GOAPNode(
            state=start_state,
            heuristic=_default_heuristic(start_state, goal),
        )
        open_set: list[GOAPNode] = [start_node]
        visited: list[tuple[Any, ...]] = []

        while open_set:
            current = heapq.heappop(open_set)

            if max_budget is not None and current.cost > max_budget:
                continue

            if _default_heuristic(current.state, goal) == 0:
                info(f"GOAP: plan found with {len(current.actions)} actions, cost={current.cost:.1f}")
                if use_cache:
                    self._plan_cache[cache_key] = current.actions
                return current.actions

            state_key = tuple(sorted(current.state.items()))
            if state_key in visited:
                continue
            visited.append(state_key)

            if len(current.actions) >= max_depth:
                continue

            for action in sorted_actions:
                if action.is_valid(current.state):
                    new_state = action.apply_effects(current.state)
                    new_cost = current.cost + action.cost
                    if max_budget is not None and new_cost > max_budget:
                        continue
                    new_node = GOAPNode(
                        state=new_state,
                        actions=current.actions + [action],
                        cost=new_cost,
                        heuristic=_default_heuristic(new_state, goal),
                    )
                    heapq.heappush(open_set, new_node)

        info("GOAP: no plan found")
        return None

    def explain(
        self,
        start_state: dict[str, Any],
        goal: dict[str, Any],
        max_depth: int = 10,
    ) -> dict[str, Any]:
        """Run the planner and explain why each action was chosen.

        Returns a dict with plan details, preconditions matched/missed per action,
        and per-action cost breakdown.
        """
        result: dict[str, Any] = {
            "start_state": start_state,
            "goal": goal,
            "plan": None,
            "actions": [],
            "total_cost": 0.0,
        }
        plan = self.plan(start_state, goal, max_depth=max_depth, use_cache=False)
        if plan is None:
            result["error"] = "no_plan_found"
            return result

        state = dict(start_state)
        action_details = []
        for action in plan:
            matched = {k: v for k, v in action.preconditions.items() if state.get(k) == v}
            missed = {k: {"expected": v, "actual": state.get(k)} for k, v in action.preconditions.items() if state.get(k) != v}
            if not missed:
                state = action.apply_effects(state)
            action_details.append({
                "name": action.name,
                "cost": action.cost,
                "priority": action.priority,
                "version": action.version,
                "preconditions": dict(action.preconditions),
                "matched": matched,
                "missed": missed,
                "effects_applied": dict(action.effects),
                "state_after": dict(state),
            })

        result["plan"] = [a.name for a in plan]
        result["actions"] = action_details
        result["total_cost"] = sum(a.cost for a in plan)
        result["final_state"] = state
        return result

    def group_independent(self, action_names: list[str]) -> list[list[str]]:
        """Group actions into parallel batches (no conflicting effects)."""
        name_map = {a.name: a for a in self._actions}
        batches: list[list[str]] = []
        used_keys: set[str] = set()
        current_batch: list[str] = []
        for name in action_names:
            action = name_map.get(name)
            if action is None:
                current_batch.append(name)
                continue
            action_keys = set(action.effects)
            if action_keys & used_keys:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [name]
                used_keys = action_keys
            else:
                current_batch.append(name)
                used_keys |= action_keys
        if current_batch:
            batches.append(current_batch)
        return batches

    def record_outcome(self, action_name: str, success: bool, elapsed_ms: float = 0.0) -> None:
        """Adjust cost based on outcome using SQLite or JSON fallback."""
        if self._learning_db:
            new_cost = self._learning_db.record_outcome(action_name, success, cost=1.0, elapsed_ms=elapsed_ms)
            self.clear_cache()
            return
        # Legacy JSON path
        current = self._cost_overrides.get(action_name, 1.0)
        if success:
            new_cost = max(0.5, current * 0.9)
        else:
            new_cost = min(5.0, current * 1.3)
        self._cost_overrides[action_name] = round(new_cost, 2)
        self._save_learning()
        self.clear_cache()
        info(f"GOAP learning: {action_name} cost {current:.2f} -> {new_cost:.2f} (success={success})")

    def rollback_learning(self, action_name: str, steps: int = 1) -> bool:
        """Rollback learning for an action. Works with SQLite backend."""
        if self._learning_db:
            return self._learning_db.rollback(action_name, steps)
        return False

    def get_learning_stats(self, action_name: str) -> dict[str, Any]:
        if self._learning_db:
            return self._learning_db.get_stats(action_name)
        return {"action_name": action_name, "current_cost": self._cost_overrides.get(action_name, 1.0)}

    def get_learning_summary(self) -> dict[str, Any]:
        if self._learning_db:
            return {
                "base_actions": [a.name for a in self._actions],
                "cost_overrides": self._learning_db.export_json(),
                "backend": "sqlite",
            }
        return {
            "base_actions": [a.name for a in self._actions],
            "cost_overrides": dict(self._cost_overrides),
            "backend": "json",
        }

    def simulate(
        self,
        start_state: dict[str, Any],
        goal: dict[str, Any],
        max_depth: int = 10,
        max_budget: float | None = None,
    ) -> dict[str, Any]:
        """What-if simulation: show what plan WOULD be executed without running it.

        Returns the plan details, cost breakdown, and alternative plans if available.
        """
        primary = self.plan(start_state, goal, max_depth=max_depth, use_cache=False, max_budget=max_budget)
        if primary is None:
            return {"status": "no_plan", "start_state": start_state, "goal": goal}

        # Generate alternative plans by disabling one action at a time
        alternatives: list[dict[str, Any]] = []
        for skip_idx in range(min(3, len(primary))):
            skipped_name = primary[skip_idx].name
            # Create a copy of actions excluding the skipped one
            saved = list(self._actions)
            self._actions = [a for a in self._actions if a.name != skipped_name]
            alt = self.plan(start_state, goal, max_depth=max_depth, use_cache=False, max_budget=max_budget)
            self._actions = saved
            if alt is not None:
                alternatives.append({
                    "without": skipped_name,
                    "actions": [a.name for a in alt],
                    "total_cost": sum(a.cost for a in alt),
                })

        actions_detail = []
        state = dict(start_state)
        for action in primary:
            state = action.apply_effects(state)
            actions_detail.append({
                "name": action.name,
                "cost": action.cost,
                "priority": action.priority,
                "version": action.version,
                "effects": dict(action.effects),
            })

        return {
            "status": "ok",
            "start_state": start_state,
            "goal": goal,
            "plan": [a.name for a in primary],
            "total_cost": sum(a.cost for a in primary),
            "num_actions": len(primary),
            "actions_detail": actions_detail,
            "alternatives": alternatives,
        }

    def _load_learning(self) -> None:
        if self._learning_db:
            return  # SQLite handles its own persistence
        try:
            if self._learning_path.exists():
                data = json.loads(self._learning_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._cost_overrides = {k: float(v) for k, v in data.items()}
        except Exception:
            self._cost_overrides = {}

    def _save_learning(self) -> None:
        if self._learning_db:
            return
        try:
            self._learning_path.write_text(
                json.dumps(self._cost_overrides, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass


# ── Multi-agent GOAP ─────────────────────────────────────────────────────────

@dataclass
class GOAPAgent:
    name: str
    planner: GOAPPlanner
    priority: int = 0  # higher = wins conflicts


class MultiAgentGOAP:
    """Runs multiple GOAP planners in parallel and resolves conflicting goals by priority."""

    def __init__(self):
        self._agents: list[GOAPAgent] = []

    def add_agent(self, agent: GOAPAgent) -> None:
        self._agents.append(agent)
        self._agents.sort(key=lambda a: -a.priority)

    def resolve(
        self,
        start_state: dict[str, Any],
        goal_map: dict[str, dict[str, Any]],
        max_depth: int = 6,
    ) -> dict[str, Any]:
        """Compute plans for each agent and merge by priority.

        Returns merged actions and per-agent results.
        """
        results: dict[str, Any] = {}
        merged_actions: list[GOAPAction] = []
        seen_keys: set[str] = set()

        for agent in self._agents:
            goal = goal_map.get(agent.name)
            if goal is None:
                continue
            plan = agent.planner.plan(start_state, goal, max_depth=max_depth)
            if plan is None:
                results[agent.name] = {"status": "no_plan", "actions": []}
                continue
            # Filter actions whose effects conflict with higher-priority agents
            filtered: list[GOAPAction] = []
            for action in plan:
                action_effects = set(action.effects)
                if action_effects & seen_keys:
                    continue  # skip conflicting action
                seen_keys |= action_effects
                filtered.append(action)
                merged_actions.append(action)
            results[agent.name] = {"status": "ok", "actions": [a.name for a in filtered]}

        return {
            "merged_actions": [a.name for a in merged_actions],
            "agents": results,
        }
