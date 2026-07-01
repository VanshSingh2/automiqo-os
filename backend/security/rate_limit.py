"""
Lightweight in-process rate limiter (review finding B2).

Dependency-free sliding-window limiter — no extra packages, no Redis needed for
the common case. It protects cost-bearing endpoints (chat, ask) from abuse /
denial-of-wallet. For multi-worker deployments this is per-worker; pair it with
an Nginx `limit_req` zone for a global cap.

Usage:
    from backend.security.rate_limit import rate_limit
    @router.post("/chat", dependencies=[Depends(rate_limit("chat", per_minute=20))])
"""
from __future__ import annotations
import os
import time
from collections import defaultdict, deque
from fastapi import Request, HTTPException

# key -> deque[timestamps]
_HITS: dict[str, deque] = defaultdict(deque)


def _enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"


def _default_limit() -> int:
    try:
        return int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    except ValueError:
        return 30


def rate_limit(bucket: str, per_minute: int | None = None):
    """Return a FastAPI dependency enforcing `per_minute` requests per client."""
    def _dep(request: Request):
        if not _enabled():
            return
        limit = per_minute if per_minute is not None else _default_limit()
        if limit <= 0:
            return
        client = request.client.host if request.client else "unknown"
        key = f"{bucket}:{client}"
        now = time.time()
        window_start = now - 60
        hits = _HITS[key]
        # drop timestamps older than the window
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= limit:
            retry = max(1, int(60 - (now - hits[0])))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit}/min). Try again in {retry}s.",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)
    return _dep
