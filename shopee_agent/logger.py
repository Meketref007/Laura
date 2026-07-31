"""logger.py - Logging estruturado com rotacao para Laura."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from shopee_agent.paths import LOGS_DIR

LOG_DIR = LOGS_DIR
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("laura")
logger.setLevel(logging.DEBUG)

if logger.hasHandlers():
    logger.handlers.clear()


def _redact_sensitive_text(text: str) -> str:
    redacted = re.sub(r"\b\d{9,}:[A-Za-z0-9_-]{20,}\b", "[redacted-token]", text)
    redacted = re.sub(r"(shop_id=)\d+", r"\1[redacted-id]", redacted)
    redacted = re.sub(r"(chat_id=)\d+", r"\1[redacted-id]", redacted)
    return redacted


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)
        return json.dumps(log_obj, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level = record.levelname[0]
        msg = record.getMessage()
        extra = ""
        if hasattr(record, "extra_data") and record.extra_data:
            extra = " | " + ", ".join(f"{k}={v}" for k, v in record.extra_data.items())
        return f"{ts} [{level}] {msg}{extra}"


# Console handler
console = logging.StreamHandler(sys.stderr)
console.setLevel(logging.INFO)
console.setFormatter(ConsoleFormatter())
logger.addHandler(console)

class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler que ignora PermissionError no rotate (Windows)."""
    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass  # outro processo segura o arquivo; continua escrevendo no atual
        except OSError:
            pass

# File handler with rotation (10MB per file, keep 5 backups)
file_handler = SafeRotatingFileHandler(
    LOG_DIR / "laura_operations.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(JSONFormatter())
logger.addHandler(file_handler)

# Separate error log
err_handler = SafeRotatingFileHandler(
    LOG_DIR / "laura_errors.log",
    mode="a",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
err_handler.setLevel(logging.WARNING)
err_handler.setFormatter(JSONFormatter())
logger.addHandler(err_handler)


def info(msg: str, **extra: Any) -> None:
    if extra:
        _log_with_extra("info", msg, **extra)
    else:
        logger.info(msg)


def debug(msg: str, **extra: Any) -> None:
    if extra:
        _log_with_extra("debug", msg, **extra)
    else:
        logger.debug(msg)


def warning(msg: str, **extra: Any) -> None:
    if extra:
        _log_with_extra("warning", msg, **extra)
    else:
        logger.warning(msg)


def error(msg: str, **extra: Any) -> None:
    if extra:
        _log_with_extra("error", msg, **extra)
    else:
        logger.error(msg)


def _log_with_extra(level: str, message: str, **extra: Any) -> None:
    record = logging.LogRecord(
        name="laura",
        level=getattr(logging, level.upper(), logging.INFO),
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.extra_data = extra
    logger.handle(record)


log_error = error  # alias used by cli_commands modules
