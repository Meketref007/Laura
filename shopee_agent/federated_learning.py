"""Multi-store (federated) learning — share learning data across stores.

Each store has its own LearningDB. The federated coordinator aggregates
cost data from multiple stores to produce a global model that benefits all.
"""

from __future__ import annotations

import json
import statistics
import threading
from pathlib import Path
from typing import Any

from shopee_agent.paths import FEDERATED_LEARNING


class FederatedLearningCoordinator:
    """Aggregates learning data from multiple store planners.

    Each store reports its cost overrides; the coordinator computes a
    weighted average and can push updated costs back to each store.
    """

    def __init__(self, db_path: str = str(FEDERATED_LEARNING)):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._store_data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._store_data = data
        except Exception:
            self._store_data = {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._store_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def report(self, store_id: str, learning_summary: dict[str, Any]) -> None:
        """Receive learning data from a store."""
        with self._lock:
            self._store_data[store_id] = {
                "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "cost_overrides": learning_summary.get("cost_overrides", {}),
                "base_actions": learning_summary.get("base_actions", []),
            }
            self._save()

    def aggregate(self) -> dict[str, Any]:
        """Compute global aggregated costs across all stores.

        For each action, takes the mean of reported costs weighted by
        number of stores that have data for that action.
        """
        with self._lock:
            action_costs: dict[str, list[float]] = {}
            for store_id, data in self._store_data.items():
                overrides = data.get("cost_overrides", {})
                if isinstance(overrides, dict):
                    for action_name, cost_info in overrides.items():
                        if isinstance(cost_info, dict):
                            cost = cost_info.get("current_cost", 1.0)
                        else:
                            cost = float(cost_info)
                        action_costs.setdefault(action_name, []).append(cost)

            global_model: dict[str, Any] = {}
            for action_name, costs in action_costs.items():
                global_model[action_name] = {
                    "mean_cost": round(statistics.mean(costs), 2),
                    "stdev_cost": round(statistics.stdev(costs), 2) if len(costs) > 1 else 0.0,
                    "num_stores": len(costs),
                    "min_cost": round(min(costs), 2),
                    "max_cost": round(max(costs), 2),
                }

            return {
                "global_model": global_model,
                "num_stores": len(self._store_data),
                "actions_tracked": len(global_model),
            }

    def get_store_count(self) -> int:
        with self._lock:
            return len(self._store_data)

    def list_stores(self) -> list[str]:
        with self._lock:
            return list(self._store_data.keys())
