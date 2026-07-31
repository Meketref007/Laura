"""Skill canary deploy — gradual rollout of new skill versions."""

from __future__ import annotations

import json
import random
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import SKILL_CANARY


class CanaryDeploy:
    """Manages canary deployments for skill versions.

    A new version starts at 10% traffic, scales up if error rate < threshold.
    """

    def __init__(self, path: str = str(SKILL_CANARY), persist: bool = True):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._canaries: dict[str, dict[str, Any]] = {}
        self._persist = persist
        if persist:
            self._load()

    def start_canary(
        self,
        skill_name: str,
        new_cls: Any,
        new_version: str = "v2",
        initial_pct: float = 10.0,
        max_error_rate: float = 5.0,
        scale_up_by: float = 10.0,
    ) -> str:
        """Start a canary deploy for a skill. Returns canary_id."""
        canary_id = f"{skill_name}_{new_version}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
        with self._lock:
            self._canaries[canary_id] = {
                "canary_id": canary_id,
                "skill_name": skill_name,
                "new_version": new_version,
                "new_cls": new_cls,
                "traffic_pct": initial_pct,
                "initial_pct": initial_pct,
                "max_error_rate": max_error_rate,
                "scale_up_by": scale_up_by,
                "status": "canary",
                "executions": {"canary": 0, "stable": 0, "canary_errors": 0, "stable_errors": 0},
                "started_at": datetime.now(UTC).isoformat(),
            }
            self._save()
        return canary_id

    def select_version(self, canary_id: str) -> tuple[Any, str]:
        """Return (cls, version_name) for a canary. 'canary' or 'stable'."""
        with self._lock:
            canary = self._canaries.get(canary_id)
            if canary is None:
                return None, ""
            pct = canary["traffic_pct"]
            is_canary = random.random() * 100 < pct
            version = "canary" if is_canary else "stable"
            if is_canary:
                return canary["new_cls"], version
            return None, version  # None means use default class

    def record_outcome(self, canary_id: str, version: str, success: bool) -> None:
        with self._lock:
            canary = self._canaries.get(canary_id)
            if canary is None:
                return
            execs = canary["executions"]
            execs[f"{version}_errors" if not success else version] += 1
            self._evaluate(canary)
            self._save()

    def _evaluate(self, canary: dict[str, Any]) -> None:
        execs = canary["executions"]
        canary_total = execs["canary"]
        stable_total = execs["stable"]
        canary_errors = execs["canary_errors"]
        stable_errors = execs["stable_errors"]

        if canary_total < 10:
            return  # not enough data

        canary_error_rate = (canary_errors / canary_total) * 100
        stable_error_rate = (stable_errors / stable_total) * 100 if stable_total else 0

        if canary_error_rate > canary["max_error_rate"]:
            canary["status"] = "rolled_back"
            canary["traffic_pct"] = 0.0
            return

        if canary_error_rate <= stable_error_rate * 1.5 or stable_total == 0:
            # Scale up
            canary["traffic_pct"] = min(100.0, canary["traffic_pct"] + canary["scale_up_by"])

        if canary["traffic_pct"] >= 100.0:
            canary["status"] = "promoted"

    def get_status(self, canary_id: str) -> dict[str, Any] | None:
        with self._lock:
            canary = self._canaries.get(canary_id)
            if canary is None:
                return None
            return {k: v for k, v in canary.items() if not k.endswith("_cls")}

    def list_canaries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in c.items() if not k.endswith("_cls")} for c in self._canaries.values()]

    def promote(self, canary_id: str) -> bool:
        """Manually promote a canary to full traffic."""
        with self._lock:
            canary = self._canaries.get(canary_id)
            if canary is None:
                return False
            canary["traffic_pct"] = 100.0
            canary["status"] = "promoted"
            self._save()
            return True

    def rollback(self, canary_id: str) -> bool:
        """Manually rollback a canary."""
        with self._lock:
            canary = self._canaries.get(canary_id)
            if canary is None:
                return False
            canary["traffic_pct"] = 0.0
            canary["status"] = "rolled_back"
            self._save()
            return True

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._canaries = data
        except Exception:
            pass

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            serializable: dict[str, Any] = {}
            for cid, canary in self._canaries.items():
                entry: dict[str, Any] = {}
                for k, v in canary.items():
                    if k.endswith("_cls"):
                        continue
                    entry[k] = v
                serializable[cid] = entry
            text = json.dumps(serializable, indent=2, ensure_ascii=False, default=str)
            self._path.write_text(text, encoding="utf-8")
        except Exception:
            pass


_default_canary = CanaryDeploy()


def get_canary() -> CanaryDeploy:
    return _default_canary
