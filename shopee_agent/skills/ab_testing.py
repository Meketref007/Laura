"""A/B testing for skills — run two versions in parallel, pick the winner."""

from __future__ import annotations

import json
import random
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import SKILL_AB_TESTS


class ABTestRegistry:
    """Manages A/B tests for skill versions.

    Each test has a control (v1) and variant (v2). The registry tracks
    outcomes and can recommend the winner.
    """

    def __init__(self, path: str = str(SKILL_AB_TESTS), persist: bool = True):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tests: dict[str, dict[str, Any]] = {}
        self._persist = persist
        if persist:
            self._load()

    def register_test(self, skill_name: str, control_cls: Any, variant_cls: Any, traffic_split: float = 0.5) -> None:
        """Register an A/B test. traffic_split = fraction of traffic for variant (v2)."""
        with self._lock:
            self._tests[skill_name] = {
                "control": control_cls.__name__,
                "variant": variant_cls.__name__,
                "control_cls": control_cls,
                "variant_cls": variant_cls,
                "traffic_split": traffic_split,
                "outcomes": {"control": {"executions": 0, "successes": 0, "total_elapsed_ms": 0.0},
                             "variant": {"executions": 0, "successes": 0, "total_elapsed_ms": 0.0}},
                "started_at": datetime.now(UTC).isoformat(),
            }
            self._save()

    def select_version(self, skill_name: str) -> tuple[Any, str]:
        """Return (skill_class, version_name) based on traffic split."""
        with self._lock:
            test = self._tests.get(skill_name)
            if test is None:
                return None, ""
            version = "variant" if random.random() < test["traffic_split"] else "control"
            cls = test[f"{version}_cls"]
            return cls, version

    def record_outcome(self, skill_name: str, version: str, success: bool, elapsed_ms: float = 0.0) -> None:
        with self._lock:
            test = self._tests.get(skill_name)
            if test is None or version not in ("control", "variant"):
                return
            outcomes = test["outcomes"][version]
            outcomes["executions"] += 1
            if success:
                outcomes["successes"] += 1
            outcomes["total_elapsed_ms"] += elapsed_ms
            self._save()

    def get_winner(self, skill_name: str, min_executions: int = 10) -> str | None:
        """Return 'control' or 'variant' based on success rate. None if insufficient data."""
        with self._lock:
            test = self._tests.get(skill_name)
            if test is None:
                return None
            c = test["outcomes"]["control"]
            v = test["outcomes"]["variant"]
            if c["executions"] < min_executions or v["executions"] < min_executions:
                return None
            c_rate = c["successes"] / c["executions"] if c["executions"] else 0
            v_rate = v["successes"] / v["executions"] if v["executions"] else 0
            return "variant" if v_rate > c_rate else "control"

    def summary(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {}
            for name, test in self._tests.items():
                result[name] = {
                    "control": test["control"],
                    "variant": test["variant"],
                    "traffic_split": test["traffic_split"],
                    "outcomes": test["outcomes"],
                    "winner": self.get_winner(name),
                }
            return result

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._tests = data
        except Exception:
            pass

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            serializable: dict[str, Any] = {}
            for name, test in self._tests.items():
                entry: dict[str, Any] = {}
                for k, v in test.items():
                    if k.endswith("_cls"):
                        continue
                    entry[k] = v
                serializable[name] = entry
            text = json.dumps(serializable, indent=2, ensure_ascii=False, default=str)
            self._path.write_text(text, encoding="utf-8")
        except Exception:
            pass


_default_ab_registry = ABTestRegistry()


def get_ab_registry() -> ABTestRegistry:
    return _default_ab_registry
