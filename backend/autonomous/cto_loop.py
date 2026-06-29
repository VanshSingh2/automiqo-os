"""
CTO Autonomous Daily Work Loop — runs at 2pm.
Proactively manages platform health every day:
- Reviews failed workflows from last 24h, queues retries
- Checks task success rate, flags regression if >20% failure
- Reviews AI costs per model, optimizes if needed
- Runs QA health check
- Rotates API key reminders
- Backs up and checks system health
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.cto.agent import CTOAgent


async def run_cto_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()

    actions_taken = []
    approvals_queued = []

    # ── 1. FAILED WORKFLOWS ──────────────────────────────────
    failed = sb.table("tasks").select("id,workflow,error,parameters,retries")\
        .eq("business_id", bid).eq("status", "failed")\
        .gte("created_at", since_24h).execute().data or []
    total_tasks = sb.table("tasks").select("id")\
        .eq("business_id", bid).gte("created_at", since_24h).execute().data or []

    failure_rate = len(failed) / max(len(total_tasks), 1)
    failed_workflows = list({t["workflow"] for t in failed})

    for task in failed[:5]:
        retries = task.get("retries", 0) or 0
        if retries < 3:
            await dispatch_action(bid, task["workflow"],
                task.get("parameters", {}),
                f"CTO daily loop: retrying failed workflow {task['workflow']} (attempt {retries+1})")
            actions_taken.append(f"retry queued: {task['workflow']}")

    # ── 2. REGRESSION DETECTION ──────────────────────────────
    if failure_rate > 0.20:
        await dispatch_action(bid, "run_regression_tests", {
            "failure_rate": round(failure_rate * 100, 1),
            "failed_workflows": failed_workflows,
        }, f"CTO daily loop: failure rate {round(failure_rate*100,1)}% — regression test triggered")
        approvals_queued.append(f"regression test: {round(failure_rate*100,1)}% failure rate")

        # Alert CEO
        from backend.events.bus import publish
        await publish(bid, "internal.ceo_alert", {
            "from": "CTO",
            "message": f"ALERT: Workflow failure rate {round(failure_rate*100,1)}% in last 24h. Workflows affected: {failed_workflows}",
        }, source="cto_daily_loop")
        actions_taken.append("CEO alerted: high failure rate")

    # ── 3. QA HEALTH CHECK ───────────────────────────────────
    await dispatch_action(bid, "run_regression_tests", {
        "scope": "smoke_test", "trigger": "daily_health_check"
    }, "CTO daily loop: daily smoke test")
    actions_taken.append("daily smoke test queued")

    # ── 4. BACKUP ────────────────────────────────────────────
    last_backup = sb.table("tasks").select("created_at").eq("business_id", bid)\
        .eq("workflow", "run_daily_backup").eq("status", "completed")\
        .gte("created_at", since_24h).execute().data or []
    if not last_backup:
        await dispatch_action(bid, "run_daily_backup", {
            "timestamp": now.isoformat()
        }, "CTO daily loop: scheduled daily backup")
        actions_taken.append("daily backup queued")

    # ── 5. MONITOR VPS HEALTH ────────────────────────────────
    await dispatch_action(bid, "monitor_vps_health", {
        "trigger": "daily_check"
    }, "CTO daily loop: VPS health check")
    actions_taken.append("VPS health check queued")

    # ── 6. CTO AGENT STRATEGIC REVIEW ────────────────────────
    try:
        agent = CTOAgent(UUID(bid))
        context = {
            "failed_tasks_24h": len(failed),
            "total_tasks_24h": len(total_tasks),
            "failure_rate_pct": round(failure_rate * 100, 1),
            "failed_workflows": failed_workflows,
        }
        resp = await agent.run(
            "Daily platform review: analyze system health, identify reliability risks, "
            "and decide what engineering improvements to prioritize today.",
            context=context,
        )
        for rec in (resp.recommendations or [])[:3]:
            await dispatch_action(bid, "generate_reflection", {
                "agent": "CTO", "observation": rec, "source": "daily_loop"
            }, "CTO daily insight")
    except Exception:
        pass

    return {
        "department": "CTO",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "failed_tasks_24h": len(failed),
        "failure_rate_pct": round(failure_rate * 100, 1),
    }
