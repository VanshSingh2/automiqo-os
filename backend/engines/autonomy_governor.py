"""
autonomy_governor — graduated-autonomy gate.

Decides whether an agent/workflow may act automatically (no human in the loop)
based on its recent reliability track record and the risk level of the action.

Design notes:
  * ``assess`` is SYNC because it is called from a synchronous verification
    path. Since ``agent_metrics.reliability`` is async, ``assess`` uses a private
    SYNC ``_recent_stats`` that does a direct best-effort Supabase query.
  * ``assess_agent`` is the async mirror that reuses ``agent_metrics.reliability``.
  * FAIL-OPEN: any internal error grants autonomy so the governor can never
    become a hard outage. It never raises.

Env knobs:
  AUTONOMY_MIN_RUNS     (int,   default 5)   — min track record for risky actions
  AUTONOMY_MIN_SUCCESS  (float, default 0.8) — min success rate to stay automatic
"""
import os
from datetime import datetime, timezone, timedelta

from backend.memory.supabase_client import get_supabase
from backend.obs import get_logger, log_event

_log = get_logger("autonomy_governor")


def _min_runs() -> int:
    try:
        return int(os.getenv("AUTONOMY_MIN_RUNS", "5"))
    except Exception:
        return 5


def _min_success() -> float:
    try:
        return float(os.getenv("AUTONOMY_MIN_SUCCESS", "0.8"))
    except Exception:
        return 0.8


def _recent_stats(business_id, workflow, window_days: int = 14):
    """SYNC best-effort ``(runs, success_rate)`` for a workflow over the window.

    On any error / empty history returns ``(0, 1.0)`` — trusting default.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        rows = (
            get_supabase().table("agent_metrics")
            .select("success")
            .eq("business_id", str(business_id))
            .eq("workflow", workflow)
            .gte("created_at", since)
            .execute().data
        ) or []
        runs = len(rows)
        if runs == 0:
            return 0, 1.0
        successes = sum(1 for r in rows if r.get("success"))
        return runs, successes / runs
    except Exception:
        return 0, 1.0


def _decide(runs: int, success_rate: float, risk_level: str) -> tuple[bool, str]:
    """Shared decision rules for sync/async assessors."""
    min_runs = _min_runs()
    min_success = _min_success()
    # Not enough track record to trust risky automatic actions.
    if runs < min_runs and risk_level in ("high", "critical"):
        return False, f"insufficient_track_record(runs={runs}<{min_runs},risk={risk_level})"
    # Recent success too low for anything but the lowest-risk actions.
    if success_rate < min_success and risk_level != "low":
        return False, f"low_success_rate({success_rate:.2f}<{min_success},risk={risk_level})"
    return True, "ok"


def assess(business_id: str, workflow: str, risk_level: str = "medium") -> dict:
    """SYNC autonomy assessment for a workflow.

    Returns ``{"allow_auto": bool, "reliability": float, "reason": str}``.
    Fail-open on error.
    """
    try:
        runs, success_rate = _recent_stats(business_id, workflow)
        allow, reason = _decide(runs, success_rate, risk_level)
        result = {"allow_auto": allow, "reliability": round(success_rate, 4), "reason": reason}
        try:
            log_event(_log, "autonomy.assess", workflow=workflow, risk=risk_level,
                      runs=runs, **result)
        except Exception:
            pass
        return result
    except Exception:
        return {"allow_auto": True, "reliability": 1.0, "reason": "governor_failopen"}


async def assess_agent(business_id, agent_name, risk_level="medium") -> dict:
    """ASYNC autonomy assessment for a specific agent (uses reliability()).

    Returns ``{"allow_auto": bool, "reliability": float, "reason": str}``.
    Fail-open on error.
    """
    try:
        from backend.engines import agent_metrics
        stats = await agent_metrics.reliability(business_id, agent_name)
        runs = int(stats.get("runs", 0) or 0)
        success_rate = float(stats.get("success_rate", 1.0) or 1.0)
        allow, reason = _decide(runs, success_rate, risk_level)
        result = {"allow_auto": allow, "reliability": round(success_rate, 4), "reason": reason}
        try:
            log_event(_log, "autonomy.assess_agent", agent=agent_name, risk=risk_level,
                      runs=runs, **result)
        except Exception:
            pass
        return result
    except Exception:
        return {"allow_auto": True, "reliability": 1.0, "reason": "governor_failopen"}
