"""Skill generation via LLM — creates Skill subclasses from natural language descriptions."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

_SKILL_TEMPLATE = '''"""Auto-generated skill: {name}"""

from shopee_agent.skills.registry import Skill

class {class_name}(Skill):
    name = "{name}"
    risk_level = "{risk_level}"
    preconditions = {preconditions}
    effects = {effects}
    cost = {cost}
    priority = {priority}
    schedule = "{schedule}"
    event_types = {event_types}

    def run(self, *args, **kwargs):
        """Auto-generated skill. Replace with real logic."""
        # TODO: implement skill logic
        return f"{{self.name}} executed"
'''


def _safe_name(text: str) -> str:
    """Convert text to a valid Python class name."""
    clean = "".join(c if c.isalnum() else " " for c in text).strip()
    parts = clean.split()
    return "".join(p.capitalize() for p in parts) + "Skill"


def generate_skill_class(
    description: str,
    preconditions: dict[str, Any] | None = None,
    effects: dict[str, Any] | None = None,
    risk_level: str = "LOW",
    cost: float = 1.0,
    priority: int = 0,
    schedule: str = "",
    event_types: list | None = None,
) -> str:
    """Generate Python source code for a Skill subclass from a natural language description.

    Returns the source code as a string.
    """
    class_name = _safe_name(description)
    name = description.lower().replace(" ", "_").replace("-", "_")[:50]

    if preconditions is None:
        preconditions = {}
    if effects is None:
        effects = {}
    if event_types is None:
        event_types = []

    source = _SKILL_TEMPLATE.format(
        name=name,
        class_name=class_name,
        description=description,
        risk_level=risk_level,
        preconditions=repr(preconditions),
        effects=repr(effects),
        cost=cost,
        priority=priority,
        schedule=schedule,
        event_types=repr(event_types),
    )
    return source


def save_skill_to_file(source: str, output_dir: str = "shopee_agent/skills/generated") -> Path:
    """Save generated skill source to a .py file and return the path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Extract class name from source
    tree = ast.parse(source)
    class_name = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            break
    if class_name is None:
        class_name = "GeneratedSkill"

    path = out_dir / f"{class_name.lower()}.py"
    path.write_text(source, encoding="utf-8")
    return path


def generate_and_register(
    description: str,
    registry: Any,
    preconditions: dict[str, Any] | None = None,
    effects: dict[str, Any] | None = None,
    risk_level: str = "LOW",
    cost: float = 1.0,
    priority: int = 0,
    schedule: str = "",
    event_types: list | None = None,
    output_dir: str = "shopee_agent/skills/generated",
) -> bool:
    """Generate a Skill class, save to file, import dynamically and register."""
    source = generate_skill_class(
        description=description,
        preconditions=preconditions,
        effects=effects,
        risk_level=risk_level,
        cost=cost,
        priority=priority,
        schedule=schedule,
        event_types=event_types,
    )
    path = save_skill_to_file(source, output_dir=output_dir)

    # Dynamic import
    import importlib.util as _util
    import sys as _sys
    module_name = path.stem
    spec = _util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        return False
    mod = _util.module_from_spec(spec)
    _sys.modules[module_name] = mod
    spec.loader.exec_module(mod)

    # Find Skill subclass
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        from shopee_agent.skills.registry import Skill as _SkillBase
        try:
            if issubclass(obj, _SkillBase) and obj is not _SkillBase:
                registry.register(obj)
                return True
        except Exception:
            continue
    return False
