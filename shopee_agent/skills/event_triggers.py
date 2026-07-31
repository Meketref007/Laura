"""Event-driven skill triggers — skills subscribed to event bus events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from shopee_agent.logger import info, warning

SkillTriggerFn = Callable[..., Any]


_TRIGGERS: dict[str, list[str]] = {}  # event_type -> [skill_names]


def register_trigger(event_type: str, skill_name: str) -> None:
    """Register a skill to be triggered automatically when an event of type is emitted."""
    _TRIGGERS.setdefault(event_type, []).append(skill_name)
    info(f"Trigger registered: event='{event_type}' -> skill='{skill_name}'")


def get_triggers(event_type: str) -> list[str]:
    return _TRIGGERS.get(event_type, [])


def list_all_triggers() -> dict[str, list[str]]:
    return dict(_TRIGGERS)


def set_triggers_from_metadata(registry: Any) -> None:
    """Scan all registered skills and register triggers for their event_types metadata."""
    for name in registry.list():
        cls = registry.get(name)
        if cls is None:
            continue
        event_types = getattr(cls, "event_types", [])
        if isinstance(event_types, str):
            event_types = [event_types]
        for et in event_types:
            register_trigger(et, name)


class EventTriggerWorker:
    """Worker that subscribes to event bus and dispatches skills on matching events."""

    def __init__(self, registry: Any, orchestrator: Any, event_bus: Any):
        self._registry = registry
        self._orchestrator = orchestrator
        self._event_bus = event_bus

    def start(self) -> None:
        if self._event_bus is None:
            return
        for event_type in _TRIGGERS:
            self._event_bus.register_handler(event_type, self._make_handler(event_type), name=f"trigger_{event_type}")
        info(f"EventTriggerWorker started: {len(_TRIGGERS)} trigger rules")

    def _make_handler(self, event_type: str) -> Callable:
        def handler(event: Any) -> None:
            skill_names = _TRIGGERS.get(event_type, [])
            for name in skill_names:
                skill = self._registry.get_or_create(name)
                if skill is None:
                    warning(f"Trigger skill '{name}' not found for event '{event_type}'")
                    continue
                try:
                    import asyncio
                    result = asyncio.run(self._orchestrator.execute_plan_async([name], context={"event": str(event)}))
                    info(f"Triggered skill '{name}' by event '{event_type}': ok={result}")
                except Exception as exc:
                    warning(f"Triggered skill '{name}' failed: {exc}")
        return handler
