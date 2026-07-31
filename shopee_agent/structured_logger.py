"""Structured logging for Laura — centralized, JSON-formatted, with levels."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class StructuredLogger:
    """Centralized structured logger with JSON and plain-text output."""

    def __init__(
        self,
        name: str,
        level: int = logging.INFO,
        json_output: bool = False,
        log_file: str = "",
    ) -> None:
        self._name = name
        self._json_output = json_output
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._logger.handlers.clear()
        self._logger.propagate = False

        if log_file:
            path = Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = RotatingFileHandler(
                str(path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
        else:
            handler = logging.StreamHandler(sys.stderr)

        handler.setLevel(level)
        handler.setFormatter(_Formatter(name=name, json_output=json_output))
        self._logger.addHandler(handler)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(msg, extra={"extra": kwargs} if kwargs else None)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(msg, extra={"extra": kwargs} if kwargs else None)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(msg, extra={"extra": kwargs} if kwargs else None)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(msg, extra={"extra": kwargs} if kwargs else None)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._logger.critical(msg, extra={"extra": kwargs} if kwargs else None)


class _Formatter(logging.Formatter):
    def __init__(self, name: str, json_output: bool) -> None:
        super().__init__()
        self._name = name
        self._json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).isoformat()
        msg = record.getMessage()
        extra = getattr(record, "extra", None) or {}

        if self._json_output:
            obj: dict[str, Any] = {
                "timestamp": ts,
                "level": record.levelname,
                "logger": self._name,
                "message": msg,
            }
            if extra:
                obj["extra"] = extra
            return json.dumps(obj, ensure_ascii=False)

        level = record.levelname
        extras = ""
        if extra:
            extras = " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return f"[{ts}] {level} {self._name}: {msg}{extras}"


root_logger = StructuredLogger("laura")

logger = root_logger
