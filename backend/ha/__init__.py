"""
backend.ha — high-availability helpers.

Lets the autonomous engine run as multiple replicas (web / worker / scheduler)
without double-firing scheduled work. The core primitive is `run_once`, a
cluster-wide one-shot lock (Redis SET NX) keyed by a time bucket, so exactly one
replica fires each scheduled unit. Fail-open by design: if Redis is unavailable
a single node still does its work, and the existing dispatch idempotency catches
any rare duplicates.
"""
from backend.ha.leader import role, run_once, NODE_ID

__all__ = ["role", "run_once", "NODE_ID"]
