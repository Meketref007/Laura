"""Skill Marketplace — package skills for sharing across stores/projects.

Skills can be exported as portable JSON packages and imported into other
registries or stores.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def export_skill_package(skill_cls: Any, include_source: bool = True) -> dict[str, Any]:
    """Export a skill class as a portable JSON package."""
    pkg = {
        "format_version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "skill": {
            "name": getattr(skill_cls, "name", skill_cls.__name__),
            "class_name": skill_cls.__name__,
            "module": getattr(skill_cls, "__module__", ""),
            "risk_level": getattr(skill_cls, "risk_level", "LOW"),
            "preconditions": dict(getattr(skill_cls, "preconditions", {})),
            "effects": dict(getattr(skill_cls, "effects", {})),
            "cost": float(getattr(skill_cls, "cost", 1.0)),
            "priority": int(getattr(skill_cls, "priority", 0)),
            "reverse_name": str(getattr(skill_cls, "reverse_name", "")),
            "sub_skills": list(getattr(skill_cls, "sub_skills", [])),
            "event_types": list(getattr(skill_cls, "event_types", [])),
            "schedule": str(getattr(skill_cls, "schedule", "")),
            "dependencies": list(getattr(skill_cls, "dependencies", [])),
        },
    }

    if include_source:
        try:
            import inspect
            pkg["source"] = inspect.getsource(skill_cls)
        except Exception:
            pkg["source"] = ""

    # Checksum
    raw = json.dumps(pkg, sort_keys=True, ensure_ascii=False)
    pkg["checksum"] = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return pkg


def import_skill_package(pkg: dict[str, Any], registry: Any) -> bool:
    """Import a skill package into a registry.

    Creates a dynamic Skill subclass from the package metadata.
    """
    skill_data = pkg.get("skill", {})
    name = skill_data.get("name", "")
    if not name:
        return False

    # Create a dynamic skill class
    from shopee_agent.skills.registry import Skill

    props = {
        "name": name,
        "risk_level": skill_data.get("risk_level", "LOW"),
        "preconditions": skill_data.get("preconditions", {}),
        "effects": skill_data.get("effects", {}),
        "cost": skill_data.get("cost", 1.0),
        "priority": skill_data.get("priority", 0),
        "reverse_name": skill_data.get("reverse_name", ""),
        "sub_skills": skill_data.get("sub_skills", []),
        "event_types": skill_data.get("event_types", []),
        "schedule": skill_data.get("schedule", ""),
        "dependencies": skill_data.get("dependencies", []),
    }

    DynamicSkill = type(
        skill_data.get("class_name", f"Imported{name.title()}Skill"),
        (Skill,),
        {**props, "run": lambda self, *a, **kw: {"ok": True, "message": f"Imported skill '{name}' executed"}},
    )

    registry.register(DynamicSkill)
    return True


def save_package(pkg: dict[str, Any], path: str) -> Path:
    """Save a skill package to a JSON file."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_package(path: str) -> dict[str, Any] | None:
    """Load a skill package from a JSON file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format_version") != "1.0":
            return None
        return data
    except Exception:
        return None
