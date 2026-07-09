"""
backend.ha.leader — role selection + cluster-wide one-shot locking.

Design (correctness-first, simpler than full leader election):
  Run N scheduler replicas. Each replica fires on schedule, but wraps every
  scheduled firing in a Redis SET-NX "run once" lock keyed by a time bucket, so
  exactly ONE replica fires each scheduled unit cluster-wide. If a replica is
  down, another still fires it (automatic failover). Workers are already N-safe
  via Redis blpop, and combined with the existing dispatch idempotency there are
  no double-sends.

Everything here is best-effort and env-driven with backward-compatible defaults.
Nothing in this module may crash startup.
"""
import os
import uuid

from backend.obs import get_logger, log_event

_log = get_logger("ha.leader")

# Short, per-process identifier so we can tell which node holds a given lock.
NODE_ID = uuid.uuid4().hex[:12]

_VALID_ROLES = ("all", "web", "worker", "scheduler")


def role() -> str:
    """
    Return this process's role: one of "all"|"web"|"worker"|"scheduler".

    Driven by env var ROLE. Default "all" preserves the historical single-process
    behavior (web + worker + scheduler all in one), so existing deployments are
    unaffected. Unknown values fall back to "all" (fail-safe / never crash).
    """
    try:
        value = os.getenv("ROLE", "all").strip().lower()
        return value if value in _VALID_ROLES else "all"
    except Exception:
        return "all"


async def run_once(key: str, ttl_seconds: int = 3600) -> bool:
    """
    Acquire a cluster-wide one-shot lock for `key`.

    Uses Redis `set(name=f"once:{key}", value=NODE_ID, nx=True, ex=ttl_seconds)`.
    Returns True if THIS node acquired the lock (the caller should proceed with
    the scheduled work), or False if another node already claimed it for this
    time bucket (the caller should skip).

    FAIL-OPEN: if Redis is unavailable or errors, we log via obs.log_event and
    return True — a single node still performs its work, and the existing
    dispatch idempotency guards against the rare duplicate. Never raises.
    """
    name = f"once:{key}"
    try:
        # Lazy import so importing this module never requires Redis, and so tests
        # can patch backend.dispatcher.queue.get_redis.
        from backend.dispatcher.queue import get_redis
        r = await get_redis()
        acquired = await r.set(name=name, value=NODE_ID, nx=True, ex=ttl_seconds)
        got = bool(acquired)
        log_event(_log, "ha.run_once", key=key, node=NODE_ID,
                  acquired=got, ttl=ttl_seconds)
        return got
    except Exception as e:
        # Fail open: proceed as if we own the lock so work still happens.
        log_event(_log, "ha.run_once_failopen", key=key, node=NODE_ID, error=str(e))
        return True
