"""
RAKSHA-FORCE — Structured Logger
─────────────────────────────────
JSON-structured logging compatible with Vercel's log aggregation.
All logs are written to stdout (captured by Vercel runtime).

Usage:
    from api.utils.logger import get_logger
    log = get_logger("sos")
    log.info("SOS created", alert_id="abc", user_id="xyz")
    log.error("DB failed", exc=str(e))
"""

import json
import logging
import sys
import time
from typing import Any


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":      int(time.time() * 1000),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Attach any extra fields passed via log.info("msg", extra={...})
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName", "task_name",
            ):
                payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class StructuredLogger:
    """Wrapper around logging.Logger to support structured keyword arguments."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def info(self, msg: str, **kwargs):
        self._logger.info(msg, extra=kwargs)

    def error(self, msg: str, **kwargs):
        self._logger.error(msg, extra=kwargs)

    def warning(self, msg: str, **kwargs):
        self._logger.warning(msg, extra=kwargs)

    def debug(self, msg: str, **kwargs):
        self._logger.debug(msg, extra=kwargs)

    def exception(self, msg: str, **kwargs):
        self._logger.exception(msg, extra=kwargs)


def get_logger(name: str) -> StructuredLogger:
    """
    Returns a JSON-structured logger for the given module/endpoint name.

    Args:
        name: Short name (e.g. 'sos', 'dispatch', 'auth')

    Returns:
        Configured StructuredLogger instance
    """
    logger = logging.getLogger(f"raksha.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return StructuredLogger(logger)
