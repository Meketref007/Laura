"""Skill registry — stores and instantiates skill classes."""

from __future__ import annotations

import builtins
import importlib
import inspect
from typing import Any


class Skill:
    """Base class for skills. Subclass and implement `run()`."""

    name: str = ""
    risk_level: str = "LOW"  # LOW | MEDIUM | HIGH
    preconditions: dict[str, Any] = {}   # state keys required for GOAP
    effects: dict[str, Any] = {}         # state changes after execution
    cost: float = 1.0                   # GOAP search cost
    priority: int = 0                   # higher = GOAP prefers this action
    reverse_name: str = ""              # skill to run for rollback/compensation
    sub_skills: list[str] = []          # composed sub-skills to execute after this one
    event_types: list[str] = []         # event types that trigger this skill automatically
    schedule: str = ""                  # cron schedule "HH:MM" UTC (e.g. "08:00")
    dependencies: list[str] = []        # skill names that must run before this one (DAG)

    def __init__(self, name: str | None = None, **kwargs: Any):
        self.name = name or self.__class__.name or self.__class__.__name__

    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()


def _resolve_dag(skill_names: list[str], registry: SkillRegistry) -> list[str]:
    """Topological sort of skills by dependencies field."""
    graph: dict[str, set[str]] = {}
    all_skills: set[str] = set(skill_names)
    for name in skill_names:
        graph.setdefault(name, set())
        cls = registry.get(name)
        if cls is None:
            continue
        deps = list(getattr(cls, "dependencies", []))
        for d in deps:
            if d in all_skills:
                graph[name].add(d)
    # Kahn's algorithm
    in_degree: dict[str, int] = {n: 0 for n in graph}
    for name, deps in graph.items():
        for d in deps:
            in_degree[name] = in_degree.get(name, 0) + 1
    queue = [n for n, deg in in_degree.items() if deg == 0]
    sorted_names: list[str] = []
    while queue:
        node = queue.pop(0)
        sorted_names.append(node)
        for other, deps in graph.items():
            if node in deps:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    queue.append(other)
    remaining = [n for n in skill_names if n not in sorted_names]
    return sorted_names + remaining


class SkillRegistry:
    """Registry for skill classes with optional instance caching."""

    def __init__(self, cache_instances: bool = True):
        self._skills: dict[str, type[Skill]] = {}
        self._instances: dict[str, Skill] = {}
        self._cache_instances = cache_instances

    def register(self, skill_cls: type[Skill]) -> None:
        name = getattr(skill_cls, "name", None) or skill_cls.__name__
        self._skills[name] = skill_cls

    def unregister(self, name: str) -> bool:
        """Remove a skill by name. Returns True if found."""
        found = name in self._skills
        self._skills.pop(name, None)
        self._instances.pop(name, None)
        return found

    def reload(self, name: str) -> bool:
        """Re-import the module of a registered skill and update the class."""
        cls = self._skills.get(name)
        if cls is None:
            return False
        module_name = getattr(cls, "__module__", None)
        if not module_name:
            return False
        try:
            mod = importlib.import_module(module_name)
            importlib.reload(mod)
            new_cls = getattr(mod, cls.__name__, None)
            if new_cls is None:
                return False
            self._skills[name] = new_cls
            self._instances.pop(name, None)
            return True
        except Exception:
            return False

    def reload_all(self) -> int:
        """Reload all registered skills. Returns count of successful reloads."""
        count = 0
        for name in list(self._skills.keys()):
            if self.reload(name):
                count += 1
        return count

    def register_instance(self, instance: Skill) -> None:
        self._skills[instance.name] = instance.__class__
        if self._cache_instances:
            self._instances[instance.name] = instance

    def get(self, name: str) -> type[Skill] | None:
        return self._skills.get(name)

    def get_or_create(self, name: str, *args: Any, **kwargs: Any) -> Skill | None:
        """Return cached instance or create+ cache a new one."""
        if self._cache_instances and name in self._instances:
            return self._instances[name]
        cls = self.get(name)
        if cls is None:
            return None
        instance = cls(*args, **kwargs)
        if self._cache_instances:
            self._instances[name] = instance
        return instance

    def create(self, name: str, *args: Any, **kwargs: Any) -> Skill | None:
        cls = self.get(name)
        if cls is None:
            return None
        return cls(*args, **kwargs)

    def clear_cache(self) -> None:
        self._instances.clear()

    def list(self) -> builtins.list[str]:
        return list(self._skills.keys())


default_registry = SkillRegistry()


async def invoke(skill: Skill, *args: Any, **kwargs: Any) -> Any:
    """Invoke a skill's run method, awaiting if it returns an awaitable."""
    result = skill.run(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
