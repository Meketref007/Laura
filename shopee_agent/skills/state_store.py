"""GOAPStateStore — persists GOAP state between cycles with diff & merge."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import GOAP_STATE


class GOAPStateStore:
    """Reads/writes GOAP state snapshot to persist progress across cycles.

    Supports diff-based merge to resolve conflicts between concurrent cycles.
    """

    def __init__(self, path: str = str(GOAP_STATE)):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    state = data.get("state", {})
                    if isinstance(state, dict):
                        return state
        except Exception:
            pass
        return {}

    def save(self, state: dict[str, Any]) -> None:
        try:
            payload = {
                "timestamp": datetime.now(UTC).isoformat(),
                "state": state,
            }
            self._path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def clear(self) -> None:
        try:
            if self._path.exists():
                self._path.unlink()
        except Exception:
            pass

    def diff(self, old: dict[str, Any], new: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Return {key: (old_value, new_value)} for changed keys."""
        changes: dict[str, tuple[Any, Any]] = {}
        all_keys = set(old) | set(new)
        for k in all_keys:
            if k not in old:
                changes[k] = (None, new[k])
            elif k not in new:
                changes[k] = (old[k], None)
            elif old[k] != new[k]:
                changes[k] = (old[k], new[k])
        return changes

    def merge(self, base: dict[str, Any], *updates: dict[str, Any]) -> dict[str, Any]:
        """Merge multiple state dicts. Later keys overwrite earlier ones."""
        merged = dict(base)
        for u in updates:
            merged.update(u)
        return merged

    def save_with_diff(self, new_state: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Save state and return diff from previous."""
        old = self.load()
        delta = self.diff(old, new_state)
        self.save(new_state)
        return delta

    def apply_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Load state, apply key overrides from patch, save and return."""
        state = self.load()
        state.update(patch)
        self.save(state)
        return state
