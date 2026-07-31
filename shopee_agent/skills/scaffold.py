"""Skill scaffolding — interactive skill creation from the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SKILL_TEMPLATE = '''"""Auto-generated skill: {name}."""

from __future__ import annotations

from typing import Any, Dict

from shopee_agent.skills.registry import Skill


class {class_name}(Skill):
    name = "{name}"
    risk_level = "{risk_level}"
    preconditions = {preconditions}
    effects = {effects}
    cost = {cost}
    priority = {priority}
    reverse_name = "{reverse_name}"
    sub_skills = {sub_skills}
    event_types = {event_types}
    schedule = "{schedule}"
    dependencies = {dependencies}

    def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Implement skill logic here."""
        return {{"ok": True, "message": "{name} executed"}}
'''


def generate_skill_source(
    name: str,
    class_name: str = "",
    risk_level: str = "LOW",
    preconditions: dict[str, Any] | None = None,
    effects: dict[str, Any] | None = None,
    cost: float = 1.0,
    priority: int = 0,
    reverse_name: str = "",
    sub_skills: list[str] | None = None,
    event_types: list[str] | None = None,
    schedule: str = "",
    dependencies: list[str] | None = None,
) -> str:
    """Generate Python source code for a new Skill class."""
    return SKILL_TEMPLATE.format(
        name=name,
        class_name=class_name or _to_class_name(name),
        risk_level=risk_level,
        preconditions=_fmt_dict(preconditions or {}),
        effects=_fmt_dict(effects or {}),
        cost=cost,
        priority=priority,
        reverse_name=reverse_name,
        sub_skills=_fmt_list(sub_skills or []),
        event_types=_fmt_list(event_types or []),
        schedule=schedule,
        dependencies=_fmt_list(dependencies or []),
    )


def write_skill_file(
    name: str,
    output_dir: str = "shopee_agent/skills",
    **kwargs: Any,
) -> Path:
    """Generate a skill file on disk and return its path."""
    class_name = _to_class_name(name)
    source = generate_skill_source(name, class_name=class_name, **kwargs)
    filename = f"{name.lower().replace(' ', '_').replace('-', '_')}.py"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(source, encoding="utf-8")
    return path


def _to_class_name(name: str) -> str:
    parts = name.replace("-", " ").replace("_", " ").split()
    return "".join(p.capitalize() for p in parts) + "Skill"


def _fmt_dict(d: dict[str, Any], indent: int = 4) -> str:
    if not d:
        return "{}"
    items = []
    for k, v in d.items():
        val = f'"{v}"' if isinstance(v, str) else str(v)
        items.append(f'{" " * indent}"{k}": {val}')
    inner = ",\n".join(items)
    return f"{{\n{inner},\n}}"


def _fmt_list(lst: list[str], indent: int = 4) -> str:
    if not lst:
        return "[]"
    items = [f'{" " * indent}"{item}"' for item in lst]
    inner = ",\n".join(items)
    return f"[\n{inner},\n]"
