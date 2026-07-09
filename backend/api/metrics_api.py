"""Accountability metrics API — per-agent reliability rollups.

Exposes the per-agent accountability metrics recorded by
``backend.engines.agent_metrics`` (table ``agent_metrics``). Everything here is
best-effort and defensive: a missing/empty table or any DB error degrades to a
safe, empty/zero shape — these endpoints never raise (never 500).
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter

router = APIRouter(tags=["metrics"])


def _cutoff(window_days) -> str:
    """ISO timestamp ``window_days`` in the past (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=int(window_days))).isoformat()


# ── Per-agent rollups ───────────────────────────────────────────────────────
@router.get("/accountability/{business_id}/agents")
async def agent_rollups(business_id: str, window_days: int = 14):
    """Per-agent reliability rollups for a business over ``window_days``.

    Best-effort: on empty/missing table or any error returns ``agents: []``.
    """
    try:
        from backend.memory.supabase_client import get_supabase
        from backend.engines import agent_metrics

        rows = (
            get_supabase().table("agent_metrics")
            .select("agent_name")
            .eq("business_id", str(business_id))
            .gte("created_at", _cutoff(window_days))
            .execute().data
        ) or []
        names = sorted({r.get("agent_name") for r in rows if r.get("agent_name")})

        agents = []
        for name in names:
            rel = await agent_metrics.reliability(business_id, name, window_days)
            agents.append({
                "agent_name": name,
                "runs": rel.get("runs", 0),
                "success_rate": rel.get("success_rate", 1.0),
                "avg_latency_ms": rel.get("avg_latency_ms", 0),
                "total_cost_usd": rel.get("total_cost_usd", 0.0),
            })
        agents.sort(key=lambda a: a["runs"], reverse=True)
        return {"window_days": int(window_days), "agents": agents}
    except Exception:
        return {"window_days": int(window_days), "agents": []}


# ── Aggregate summary ───────────────────────────────────────────────────────
@router.get("/accountability/{business_id}/summary")
async def accountability_summary(business_id: str, window_days: int = 14):
    """Aggregate totals across all agents for a business over ``window_days``.

    Best-effort: on empty/missing table or any error returns zeros.
    """
    zeros = {
        "total_runs": 0,
        "overall_success_rate": 0.0,
        "total_cost_usd": 0.0,
        "avg_latency_ms": 0,
        "agent_count": 0,
        "window_days": int(window_days),
    }
    try:
        from backend.memory.supabase_client import get_supabase

        rows = (
            get_supabase().table("agent_metrics")
            .select("agent_name,success,latency_ms,cost_usd,created_at")
            .eq("business_id", str(business_id))
            .gte("created_at", _cutoff(window_days))
            .execute().data
        ) or []
        total_runs = len(rows)
        if total_runs == 0:
            return zeros
        successes = sum(1 for r in rows if r.get("success"))
        latencies = [float(r.get("latency_ms") or 0) for r in rows]
        costs = [float(r.get("cost_usd") or 0) for r in rows]
        agent_count = len({r.get("agent_name") for r in rows if r.get("agent_name")})
        return {
            "total_runs": total_runs,
            "overall_success_rate": successes / total_runs,
            "total_cost_usd": round(sum(costs), 6),
            "avg_latency_ms": sum(latencies) / total_runs,
            "agent_count": agent_count,
            "window_days": int(window_days),
        }
    except Exception:
        return zeros


# ── Recent raw rows ─────────────────────────────────────────────────────────
@router.get("/accountability/{business_id}/recent")
async def recent_metrics(business_id: str, limit: int = 50):
    """Most recent raw metric rows for a business (newest first).

    Best-effort: on empty/missing table or any error returns ``[]``.
    """
    try:
        from backend.memory.supabase_client import get_supabase

        rows = (
            get_supabase().table("agent_metrics")
            .select("agent_name,event,workflow,latency_ms,cost_usd,success,trace_id,created_at")
            .eq("business_id", str(business_id))
            .order("created_at", desc=True)
            .limit(int(limit))
            .execute().data
        ) or []
        return list(rows)
    except Exception:
        return []
