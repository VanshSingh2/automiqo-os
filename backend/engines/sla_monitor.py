"""
SLA / Escalation Timers — surface work that has been sitting too long.

A real organization chases stale items: recommendations that wait too long for
owner approval, and tasks that get stuck queued/running. This engine sweeps for
those and escalates them (alerts + priority bump + timeout-fail) so nothing
silently rots.

Contract:
    await sweep(business_id) -> {"stale_recommendations": n,
                                 "stuck_tasks": m,
                                 "escalated": k}
    await sweep_all()        -> aggregate across all active businesses

Everything here is BEST-EFFORT and defensive: each sub-part is wrapped in its
own try/except so one failing branch never skips the other, and any DB access
failure is swallowed (never raises). Thresholds are env-driven.

Env vars:
    SLA_RECOMMENDATION_HOURS (int, default 24) — a 'pending' recommendation older
                             than this is stale and gets escalated.
    SLA_TASK_MINUTES         (int, default 30) — a 'queued'/'running' task older
                             than this is stuck and gets an alert. Beyond
                             SLA_TASK_MINUTES*4 it is force-failed (error=
                             'sla_timeout') so the retry/monitoring path sees it.

No new DB tables — reuses recommendations / tasks / notifications_log.
"""
from datetime import datetime, timezone

from backend.obs import get_logger, log_event

_log = get_logger("engines.sla")


def _env_int(name: str, default: int) -> int:
    """Read an int env var, best-effort (never raises)."""
    try:
        import os
        val = os.getenv(name)
        return int(val) if val is not None else default
    except Exception:
        return default


def _parse_ts(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime. None on failure."""
    try:
        if not value:
            return None
        s = str(value).strip()
        # Support a trailing 'Z' (Zulu) which fromisoformat rejects on 3.10.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _age_seconds(value, now: datetime):
    """Age in seconds of an ISO timestamp relative to `now`. None if unparseable."""
    dt = _parse_ts(value)
    if dt is None:
        return None
    try:
        return (now - dt).total_seconds()
    except Exception:
        return None


async def sweep(business_id: str) -> dict:
    """
    Best-effort SLA sweep for a single business.

    Returns counts; never raises. Each sub-part (recommendations, tasks) is
    isolated so a failure in one still lets the other run.
    """
    result = {"stale_recommendations": 0, "stuck_tasks": 0, "escalated": 0}
    now = datetime.now(timezone.utc)

    rec_hours = _env_int("SLA_RECOMMENDATION_HOURS", 24)
    task_minutes = _env_int("SLA_TASK_MINUTES", 30)
    rec_max_secs = rec_hours * 3600
    task_max_secs = task_minutes * 60
    task_fail_secs = task_max_secs * 4

    # ── Part 1: stale pending recommendations ───────────────────────────────
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        rows = sb.table("recommendations") \
            .select("id,title,status,priority,created_at") \
            .eq("business_id", business_id).eq("status", "pending") \
            .execute().data or []
        for row in rows:
            try:
                if str(row.get("status")) != "pending":
                    continue
                age = _age_seconds(row.get("created_at"), now)
                if age is None or age < rec_max_secs:
                    continue
                title = row.get("title") or "(untitled)"
                rec_id = row.get("id")
                # Alert the owner via the internal notifications channel.
                try:
                    sb.table("notifications_log").insert({
                        "business_id": business_id,
                        "channel": "internal",
                        "message": f"SLA: recommendation '{title}' pending >{rec_hours}h",
                        "status": "sent",
                    }).execute()
                except Exception:
                    pass
                # Bump priority so it floats to the top of the owner's queue.
                try:
                    sb.table("recommendations").update({"priority": "high"}) \
                        .eq("id", rec_id).execute()
                except Exception:
                    pass
                result["stale_recommendations"] += 1
                result["escalated"] += 1
            except Exception:
                continue
    except Exception:
        pass

    # ── Part 2: stuck queued/running tasks ──────────────────────────────────
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        rows = sb.table("tasks") \
            .select("id,workflow,status,created_at") \
            .eq("business_id", business_id) \
            .in_("status", ["queued", "running"]) \
            .execute().data or []
        for row in rows:
            try:
                if str(row.get("status")) not in ("queued", "running"):
                    continue
                age = _age_seconds(row.get("created_at"), now)
                if age is None or age < task_max_secs:
                    continue
                task_id = row.get("id")
                workflow = row.get("workflow") or "(unknown)"
                mins = int(age // 60)
                # Alert on every stuck task.
                try:
                    sb.table("notifications_log").insert({
                        "business_id": business_id,
                        "channel": "internal",
                        "message": (
                            f"SLA: task '{workflow}' stuck in "
                            f"{row.get('status')} >{task_minutes}m ({mins}m)"
                        ),
                        "status": "sent",
                    }).execute()
                except Exception:
                    pass
                result["stuck_tasks"] += 1
                # Beyond 4x the threshold: force-fail so retry/monitoring sees it.
                if age >= task_fail_secs:
                    try:
                        sb.table("tasks").update({
                            "status": "failed",
                            "error": "sla_timeout",
                        }).eq("id", task_id).execute()
                        result["escalated"] += 1
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass

    log_event(_log, "sla.sweep", business_id=business_id,
              stale_recommendations=result["stale_recommendations"],
              stuck_tasks=result["stuck_tasks"], escalated=result["escalated"])
    return result


async def sweep_all() -> dict:
    """
    Run the SLA sweep for every active business and aggregate the counts.

    Best-effort: a failure fetching businesses or sweeping any single business
    never raises.
    """
    agg = {"stale_recommendations": 0, "stuck_tasks": 0, "escalated": 0, "businesses": 0}

    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        rows = sb.table("businesses").select("id").eq("active", True).execute().data or []
    except Exception:
        rows = []

    for r in rows:
        try:
            bid = str(r.get("id"))
            if not bid:
                continue
            res = await sweep(bid)
            agg["stale_recommendations"] += res.get("stale_recommendations", 0)
            agg["stuck_tasks"] += res.get("stuck_tasks", 0)
            agg["escalated"] += res.get("escalated", 0)
            agg["businesses"] += 1
        except Exception:
            continue

    log_event(_log, "sla.sweep_all", **agg)
    return agg
