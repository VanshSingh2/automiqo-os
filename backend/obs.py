"""
obs — tiny structured logging helper.

Single-line, JSON-ish log format so log lines are greppable and machine-parseable
without pulling in a heavy logging framework. Level is driven by env LOG_LEVEL
(default INFO). Everything here is best-effort and must never crash a caller.
"""
import os
import json
import time
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



def now_ms() -> int:
    """Monotonic clock in integer milliseconds — for measuring latency.

    Uses a monotonic source so it is immune to wall-clock adjustments. Best
    effort: on the (very unlikely) chance the clock read fails, returns 0.
    """
    try:
        return int(time.monotonic() * 1000)
    except Exception:
        return 0


class timed:
    """Context manager that measures elapsed monotonic milliseconds.

    Never raises. Usage:

        with timed() as t:
            do_work()
        latency_ms = t.ms
    """

    def __init__(self):
        self.ms = 0
        self._start = 0

    def __enter__(self) -> "timed":
        self._start = now_ms()
        return self

    def __exit__(self, *exc) -> bool:
        try:
            self.ms = max(0, now_ms() - self._start)
        except Exception:
            self.ms = 0
        # Do not suppress exceptions from the wrapped block.
        return False


async def record_agent_run(business_id, agent_name, trace_id, latency_ms, success,
                           cost_usd: float = 0.0, workflow=None) -> None:
    """Best-effort forward of an agent-run metric to agent_metrics.record.

    Imports agent_metrics lazily inside the call to avoid a hard import cycle
    (obs is a low-level module imported widely). Never raises.
    """
    try:
        from backend.engines import agent_metrics
        await agent_metrics.record(
            business_id,
            agent_name,
            "agent.run",
            workflow=workflow,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            success=success,
            trace_id=trace_id,
        )
    except Exception:
        pass
