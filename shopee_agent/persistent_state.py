from __future__ import annotations

import json
import time
from pathlib import Path


class PersistentState:
    """Persiste timestamps de tarefas periodicas em disco para sobreviver a restarts."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data: dict[str, float] = {}
        self._carregar()

    def _carregar(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
            except Exception:
                self._data = {}

    def salvar(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, key: str, default: float = 0.0) -> float:
        return self._data.get(key, default)

    def set(self, key: str, value: float | None = None) -> None:
        self._data[key] = value if value is not None else time.time()

    def update_and_save(self, key: str, value: float | None = None) -> None:
        self.set(key, value)
        self.salvar()
