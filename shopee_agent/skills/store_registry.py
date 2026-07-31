"""Multi-store / multi-tenant support — isolated registries and planners per store."""

from __future__ import annotations

from typing import Any

from shopee_agent.goap_planner import GOAPPlanner
from shopee_agent.skills.registry import SkillRegistry


class StoreContext:
    """Isolated context for a single store/tenant."""

    def __init__(self, store_id: str, registry: SkillRegistry | None = None):
        self.store_id = store_id
        self.registry = registry or SkillRegistry()
        self.planner = GOAPPlanner(learning_path=f"reports/goap_learning_{store_id}.json")
        self.planner.load_skills(self.registry)
        self.metadata: dict[str, Any] = {}

    def summary(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "skills": self.registry.list(),
            "learning_path": str(self.planner._learning_path),
            "metadata": self.metadata,
        }


class StoreRegistry:
    """Manages multiple StoreContext instances, one per store."""

    def __init__(self):
        self._stores: dict[str, StoreContext] = {}

    def get_or_create(self, store_id: str) -> StoreContext:
        if store_id not in self._stores:
            self._stores[store_id] = StoreContext(store_id)
        return self._stores[store_id]

    def get(self, store_id: str) -> StoreContext | None:
        return self._stores.get(store_id)

    def remove(self, store_id: str) -> None:
        self._stores.pop(store_id, None)

    def list_stores(self) -> dict[str, StoreContext]:
        return dict(self._stores)

    def list_store_ids(self) -> list:
        return list(self._stores.keys())

    def summaries(self) -> dict[str, Any]:
        return {sid: ctx.summary() for sid, ctx in self._stores.items()}


_default_store_registry = StoreRegistry()


def get_store_registry() -> StoreRegistry:
    return _default_store_registry
