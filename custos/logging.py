"""
CUSTOS Structured Logging

JSON-formatted logging for all CUSTOS events.
Every log entry is a valid JSON object parseable by
log aggregators (Datadog, Loki, CloudWatch, etc).

Usage:
    from custos.logging import get_logger
    logger = get_logger(__name__)
    logger.info("evaluate.allow", extra={"client_id": "default", "action": "allow"})
"""

import json
import logging
import sys
import time
from typing import Any


class CUSTOSFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    LEVEL_MAP = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warning",
        logging.ERROR: "error",
        logging.CRITICAL: "critical",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)
            ),
            "level": self.LEVEL_MAP.get(record.levelno, "info"),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach any extra fields passed via the `extra` kwarg
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "id", "levelname", "levelno",
                "lineno", "module", "msecs", "message", "msg", "name",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName", "taskName",
            ):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Call once at startup to configure the root CUSTOS logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CUSTOSFormatter())

    root = logging.getLogger("custos")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a custos-namespaced logger."""
    return logging.getLogger(f"custos.{name}" if not name.startswith("custos") else name)
