"""
agent_metrics — per-agent accountability metrics.

Best-effort recording of agent activity plus reliability scoring, backed by a
Supabase table ``agent_metrics``. Everything here is defensive:

  * callers are NEVER crashed (all DB work wrapped in try/except),
  * a missing table / empty history degrades to safe, *trusting* defaults —
    a brand-new agent with no track record is trusted by default.

The Supabase client is synchronous; like the rest of the codebase we make the
synchronous DB calls inline inside the async functions.

Table DDL (see module bottom / task report):
    agent_metrics(business_id, agent_name, event, workflow, latency_ms,
                  cost_usd, success, trace_id, created_at)
"""
from datetime import datetime, timezone, timedelta

from backend.memory.supabase_client import get_supabase
from backend.obs import get_logger, log_event

_log = get_logger("agent_metrics")

# A brand-new agent (no rows) is trusted: success_rate 1.0, zero cost/latency.
_DEFAULT_RELIABILITY = {
    "runs": 0,
    "success_rate": 1.0,
    "avg_latency_ms": 0,
    "total_cost_usd": 0.0,
}


async def record(business_id, agent_name, event, workflow=None, latency_ms=None,
                 cost_usd=None, success=True, trace_id=None) -> None:
    """Best-effort insert of one metric row into ``agent_metrics``.

    On any error (table absent, no client, network) this no-ops. Also emits a
    structured obs ``agent.metric`` line regardless of DB outcome.
    """
    row = {
        "business_id": str(business_id) if business_id is not None else None,
        "agent_name": agent_name,
        "event": event,
        "workflow": workflow,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "success": bool(success),
        "trace_id": trace_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_supabase().table("agent_metrics").insert(row).execute()
    except Exception:
        # Missing table / offline / client error — accountability is best-effort.
        pass
    # Structured log line is independent of DB success so we never lose signal.
    try:
        log_event(
            _log, "agent.metric",
            agent=agent_name, event=event, workflow=workflow,
            latency_ms=latency_ms, cost_usd=cost_usd, success=bool(success),
            trace_id=trace_id,
            business_id=str(business_id) if business_id is not None else None,
        )
    except Exception:
        pass


async def reliability(business_id, agent_name, window_days=14) -> dict:
    """Reliability stats for ``agent_name`` over the last ``window_days``.

    Returns ``{runs, success_rate (0..1), avg_latency_ms, total_cost_usd}``.
    When the table/rows are absent or any error occurs, returns trusting
    defaults (runs=0, success_rate=1.0) — new agents are trusted by default.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=int(window_days))).isoformat()
        rows = (
            get_supabase().table("agent_metrics")
            .select("success,latency_ms,cost_usd")
            .eq("business_id", str(business_id))
            .eq("agent_name", agent_name)
            .gte("created_at", since)
            .execute().data
        ) or []
        runs = len(rows)
        if runs == 0:
            return dict(_DEFAULT_RELIABILITY)
        successes = sum(1 for r in rows if r.get("success"))
        latencies = [float(r.get("latency_ms") or 0) for r in rows]
        costs = [float(r.get("cost_usd") or 0) for r in rows]
        return {
            "runs": runs,
            "success_rate": successes / runs,
            "avg_latency_ms": sum(latencies) / runs,
            "total_cost_usd": round(sum(costs), 6),
        }
    except Exception:
        return dict(_DEFAULT_RELIABILITY)
