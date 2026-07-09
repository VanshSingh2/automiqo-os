"""
obs — tiny structured logging helper.

Single-line, JSON-ish log format so log lines are greppable and machine-parseable
without pulling in a heavy logging framework. Level is driven by env LOG_LEVEL
(default INFO). Everything here is best-effort and must never crash a caller.
"""
import os
import json
import uuid
import logging

_CONFIGURED: set[str] = set()


class _SingleLineFormatter(logging.Formatter):
    """Formats a record as: <ts> <level> <name> <message> k=v k=v ..."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")
        base = f"{ts} {record.levelname} {record.name} {record.getMessage()}"
        # Any extra fields attached to the record become k=v pairs.
        extra = getattr(record, "_fields", None)
        if extra:
            try:
                parts = []
                for k, v in extra.items():
                    if not isinstance(v, (str, int, float, bool)) and v is not None:
                        v = json.dumps(v, default=str)
                    parts.append(f"{k}={v}")
                if parts:
                    base = base + " " + " ".join(parts)
            except Exception:
                pass
        return base


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger configured once with a single-line formatter."""
    logger = logging.getLogger(name)
    if name not in _CONFIGURED:
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        logger.setLevel(level)
        # Only attach our own handler once; don't double-log via root.
        handler = logging.StreamHandler()
        handler.setFormatter(_SingleLineFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        _CONFIGURED.add(name)
    return logger


def new_trace_id() -> str:
    """Short uuid4 hex (12 chars) for correlating a unit of work."""
    return uuid.uuid4().hex[:12]


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    """Emit one structured line: event=<event> k=v k=v ... — never raises."""
    try:
        payload = {"event": event, **fields}
        logger.info(event, extra={"_fields": payload})
    except Exception:
        pass
