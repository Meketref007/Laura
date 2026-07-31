"""Dynamic loader — discovers and registers skill classes."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from .registry import Skill, SkillRegistry, default_registry


def discover_and_register(
    package: str = "shopee_agent.skills",
    registry: SkillRegistry | None = None,
) -> None:
    """Discover Skill subclasses in a package and register them."""
    if registry is None:
        registry = default_registry

    pkg = importlib.import_module(package)
    if not hasattr(pkg, "__path__"):
        return

    for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
        full_name = f"{package}.{name}"
        try:
            mod = importlib.import_module(full_name)
        except Exception:
            continue

        for _member_name, obj in inspect.getmembers(mod, inspect.isclass):
            try:
                if issubclass(obj, Skill) and obj is not Skill:
                    registry.register(obj)
            except Exception:
                continue
