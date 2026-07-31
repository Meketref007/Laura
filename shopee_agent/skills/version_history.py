"""Skill Version History — tracks changes to skill source code and configuration over time."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import SKILL_VERSIONS


class SkillVersionHistory:
    """Tracks versions of skill source and metadata.

    Each time a skill is registered or reloaded, a snapshot is recorded.
    """

    def __init__(self, db_path: str = str(SKILL_VERSIONS)):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._versions: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._versions = data
        except Exception:
            self._versions = {}

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._versions, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def record(self, skill_name: str, source: str = "", metadata: dict[str, Any] | None = None) -> str:
        """Record a new version. Returns version hash."""
        version_hash = hashlib.sha256(source.encode()).hexdigest()[:12]
        entry = {
            "version": version_hash,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_preview": source[:500],
            "source_length": len(source),
            "metadata": metadata or {},
        }
        with self._lock:
            if skill_name not in self._versions:
                self._versions[skill_name] = []
            self._versions[skill_name].append(entry)
            # Keep only last 20 versions per skill
            if len(self._versions[skill_name]) > 20:
                self._versions[skill_name] = self._versions[skill_name][-20:]
            self._save()
        return version_hash

    def get_history(self, skill_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._versions.get(skill_name, []))

    def get_all_summary(self) -> dict[str, Any]:
        with self._lock:
            result = {}
            for name, versions in self._versions.items():
                result[name] = {
                    "total_versions": len(versions),
                    "latest": versions[-1] if versions else None,
                    "first": versions[0] if versions else None,
                }
            return result

    def rollback(self, skill_name: str, target_version: str) -> dict[str, Any] | None:
        """Restore source from a specific version."""
        with self._lock:
            versions = self._versions.get(skill_name, [])
            for v in versions:
                if v["version"] == target_version:
                    return dict(v)
        return None


_default_history = SkillVersionHistory()


def get_skill_history() -> SkillVersionHistory:
    return _default_history
