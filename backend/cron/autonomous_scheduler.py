"""
Autonomous Scheduler — runs inside the FastAPI lifespan as a background task.
Replaces the need for n8n crons for department work triggers.
Each department fires at its scheduled hour (configurable via env vars).

Schedule (EST):
  06:00 — COO   (appointments, reminders, no-shows, inventory)
  08:00 — CMO   (leads, campaigns, social)
  09:00 — CRO   (dormant, upsells, missed calls, payments)
  10:00 — CFO   (revenue, costs, purchase orders)
  14:00 — CTO   (failed workflows, backup, health check)
  15:00 — CSD   (reviews, churn, surveys, loyalty)
  22:00 — Learning (calls, failures, experiments, nightly reflection)
  *:00  — Heartbeat every 60 minutes (all depts scan for urgent work)
  07:00 — CEO   (daily standup via daily.standup event)
"""
import os
import asyncio
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase
from backend.events.bus import publish, E

# Department schedule: dept_key → (hour_est, loop_fn_path)
DEPT_SCHEDULE = {
    "coo":      (int(os.getenv("DEPT_SCHEDULE_COO", "6")),  "backend.autonomous.coo_loop.run_coo_daily_loop"),
    "cmo":      (int(os.getenv("DEPT_SCHEDULE_CMO", "8")),  "backend.autonomous.cmo_loop.run_cmo_daily_loop"),
    "cro":      (int(os.getenv("DEPT_SCHEDULE_CRO", "9")),  "backend.autonomous.cro_loop.run_cro_daily_loop"),
    "cfo":      (int(os.getenv("DEPT_SCHEDULE_CFO", "10")), "backend.autonomous.cfo_loop.run_cfo_daily_loop"),
    "cto":      (int(os.getenv("DEPT_SCHEDULE_CTO", "14")), "backend.autonomous.cto_loop.run_cto_daily_loop"),
    "csd":      (int(os.getenv("DEPT_SCHEDULE_CSD", "15")), "backend.autonomous.csd_loop.run_csd_daily_loop"),
    "learning": (int(os.getenv("DEPT_SCHEDULE_LEARNING", "22")), "backend.autonomous.learning_loop.run_learning_daily_loop"),
}
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "60"))
URGENT_SCAN_INTERVAL = int(os.getenv("URGENT_SCAN_INTERVAL_MINUTES", "5"))
CEO_STANDUP_HOUR = 7


def _utc_to_est_hour(utc_dt: datetime) -> int:
    """Rough EST offset (UTC-5, ignores DST for simplicity)."""
    return (utc_dt.hour - 5) % 24


def _seconds_until_next_hour(target_hour_est: int, now_utc: datetime) -> float:
    """Return seconds until the next occurrence of target_hour in EST."""
    now_est_hour = _utc_to_est_hour(now_utc)
    now_est_minute = now_utc.minute
    hours_ahead = (target_hour_est - now_est_hour) % 24
    if hours_ahead == 0 and now_est_minute > 0:
        hours_ahead = 24  # already past this hour today
    return hours_ahead * 3600 - now_est_minute * 60 - now_utc.second


async def _get_all_active_businesses() -> list[str]:
    """Return list of active business_ids."""
    try:
        sb = get_supabase()
        result = sb.table("businesses").select("id").eq("active", True).execute()
        return [str(r["id"]) for r in (result.data or [])]
    except Exception as e:
        print(f"[scheduler] Could not fetch businesses: {e}")
        return []


async def _get_active_businesses_with_config() -> list[dict]:
    """Return active businesses as [{'id':..., 'config':...}] for module gating."""
    try:
        sb = get_supabase()
        result = sb.table("businesses").select("id,config").eq("active", True).execute()
        return [{"id": str(r["id"]), "config": r.get("config") or {}} for r in (result.data or [])]
    except Exception as e:
        print(f"[scheduler] Could not fetch businesses: {e}")
        return []


async def _run_dept_loop(dept: str, fn_path: str, business_id: str):
    """Import and run a dept loop function."""
    module_path, fn_name = fn_path.rsplit(".", 1)
    try:
        import importlib
        module = importlib.import_module(module_path)
        fn = getattr(module, fn_name)
        result = await fn(business_id)
        actions = result.get("actions_taken", 0)
        queued = result.get("approvals_queued", 0)
        print(f"[scheduler][{dept.upper()}][{business_id[:8]}] done — "
              f"{actions} actions, {queued} queued for approval")
        # Post a human-readable standup line into the team chat.
        try:
            from backend.events.agent_chat import post_team_message
            if actions or queued:
                msg = (f"Daily routine done — handled {actions} task(s) automatically"
                       + (f" and queued {queued} for your approval." if queued else "."))
            else:
                msg = "Daily routine done — everything looks healthy, nothing needed action."
            await post_team_message(business_id, dept, msg, category="standup")
        except Exception:
            pass
    except Exception as e:
        print(f"[scheduler][{dept.upper()}] Error: {e}")


async def _dept_scheduler(dept: str, target_hour_est: int, fn_path: str):
    """Per-department scheduler loop — fires once per day at the configured hour."""
    print(f"[scheduler] {dept.upper()} scheduled at {target_hour_est}:00 EST")
    while True:
        now = datetime.now(timezone.utc)
        wait = _seconds_until_next_hour(target_hour_est, now)
        await asyncio.sleep(wait)

        businesses = await _get_active_businesses_with_config()
        if not businesses:
            continue

        # Only fire for businesses where THIS department is enabled in their blueprint.
        from backend.engines.business_blueprint import is_dept_enabled
        active = [b for b in businesses if is_dept_enabled(b["config"], dept)]
        skipped = len(businesses) - len(active)
        if not active:
            print(f"[scheduler] {dept.upper()} not enabled for any business — skipping")
            await asyncio.sleep(23 * 3600)
            continue

        note = f" ({skipped} skipped: module off)" if skipped else ""
        print(f"[scheduler] ⏰ {dept.upper()} daily loop firing for {len(active)} business(es){note}")
        await asyncio.gather(
            *[_run_dept_loop(dept, fn_path, b["id"]) for b in active],
            return_exceptions=True,
        )

        # Also publish dept.work event for any event-driven subscribers
        for b in active:
            await publish(b["id"], f"dept.work.{dept}", {"triggered_by": "scheduler"}, source="scheduler")

        # Sleep 23h to avoid double-firing
        await asyncio.sleep(23 * 3600)


async def _ceo_standup_scheduler():
    """CEO daily standup at 7am EST — fires daily.standup event for all businesses."""
    print(f"[scheduler] CEO standup scheduled at {CEO_STANDUP_HOUR}:00 EST")
    while True:
        now = datetime.now(timezone.utc)
        wait = _seconds_until_next_hour(CEO_STANDUP_HOUR, now)
        await asyncio.sleep(wait)

        businesses = await _get_all_active_businesses()
        print(f"[scheduler] ⏰ CEO daily standup firing for {len(businesses)} business(es)")
        for bid in businesses:
            await publish(bid, E.DAILY_STANDUP, {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "triggered_by": "scheduler",
            }, source="scheduler")
            # CEO opens the team chat for the day.
            try:
                from backend.events.agent_chat import post_team_message
                await post_team_message(
                    bid, "ceo",
                    "Good morning team — daily standup. Each department, please review "
                    "yesterday and share today's focus. Flag anything that needs the owner.",
                    category="standup",
                )
            except Exception:
                pass

        await asyncio.sleep(23 * 3600)


async def _urgent_scanner():
    """
    Scans every 5 minutes for the most time-critical signals.
    These CANNOT wait 60 minutes:
      - Missed calls (customer hung up, recover within 5 min)
      - Failed payments (recover before card expires)
      - Negative reviews posted (respond within minutes)
      - High-priority task failures (outage-level)
    """
    from backend.events.bus import publish, E
    from backend.memory.supabase_client import get_supabase
    print(f"[scheduler] Urgent scanner every {URGENT_SCAN_INTERVAL}min")

    while True:
        await asyncio.sleep(URGENT_SCAN_INTERVAL * 60)
        businesses = await _get_all_active_businesses()

        for bid in businesses:
            try:
                sb = get_supabase()
                now = datetime.now(timezone.utc)
                window = (now - timedelta(minutes=URGENT_SCAN_INTERVAL + 1)).isoformat()

                # ── Missed calls in last 5 min ──────────────────────────
                missed = sb.table("calls").select("id,caller_phone,called_at") \
                    .eq("business_id", bid).eq("status", "missed") \
                    .gte("called_at", window).execute().data or []
                for call in missed:
                    await publish(bid, E.CALL_MISSED, {
                        "customer_phone": call.get("caller_phone"),
                        "call_id": call["id"],
                        "called_at": call.get("called_at"),
                        "urgency": "high",
                    }, source="urgent_scanner")

                # ── New failed payments in last 5 min ───────────────────
                failed_pay = sb.table("tasks").select("id,parameters,created_at") \
                    .eq("business_id", bid) \
                    .in_("workflow", ["recover_failed_payment", "send_payment_link"]) \
                    .eq("status", "failed").gte("created_at", window).execute().data or []
                for task in failed_pay:
                    await publish(bid, E.PAYMENT_FAILED, {
                        **(task.get("parameters") or {}),
                        "urgency": "high",
                    }, source="urgent_scanner")

                # ── Negative calls/reviews in last 5 min ────────────────
                neg_calls = sb.table("calls").select("id,customer_id,sentiment,summary") \
                    .eq("business_id", bid).eq("sentiment", "negative") \
                    .gte("called_at", window).execute().data or []
                for call in neg_calls:
                    await publish(bid, E.REVIEW_NEGATIVE, {
                        "call_id": call["id"],
                        "customer_id": call.get("customer_id"),
                        "review_text": call.get("summary", ""),
                        "source": "call_sentiment",
                        "urgency": "high",
                    }, source="urgent_scanner")

                # ── Critical task failures (failed in last 5 min) ───────
                critical_fails = sb.table("tasks").select("id,workflow,error") \
                    .eq("business_id", bid).eq("status", "failed") \
                    .gte("created_at", window).execute().data or []
                # Only alert CTO if more than 2 failures in this window
                if len(critical_fails) >= 2:
                    await publish(bid, E.WORKFLOW_FAILED, {
                        "count": len(critical_fails),
                        "workflows": [t["workflow"] for t in critical_fails],
                        "urgency": "high",
                    }, source="urgent_scanner")

                if missed or failed_pay or neg_calls or len(critical_fails) >= 2:
                    print(f"[urgent][{bid[:8]}] missed_calls={len(missed)} "
                          f"failed_pay={len(failed_pay)} neg_calls={len(neg_calls)} "
                          f"task_fails={len(critical_fails)}")

            except Exception as e:
                print(f"[urgent_scanner] Error for {bid[:8]}: {e}")


async def _heartbeat_scheduler():
    """Heartbeat every HEARTBEAT_INTERVAL minutes — scans all depts for urgent work."""
    from backend.events.worker import run_hourly_heartbeat
    print(f"[scheduler] Heartbeat every {HEARTBEAT_INTERVAL}min")
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL * 60)
        businesses = await _get_all_active_businesses()
        for bid in businesses:
            try:
                result = await run_hourly_heartbeat(bid)
                total = sum(result.values())
                if total > 0:
                    print(f"[heartbeat][{bid[:8]}] {result}")
            except Exception as e:
                print(f"[heartbeat] Error for {bid[:8]}: {e}")


async def start_autonomous_scheduler():
    """
    Launch all scheduler tasks. Called from main.py lifespan.
    Returns list of asyncio.Tasks so they can be cancelled on shutdown.
    """
    if os.getenv("AUTONOMOUS_MODE", "true").lower() == "false":
        print("[scheduler] AUTONOMOUS_MODE=false — skipping")
        return []

    tasks = []

    # One scheduler per department
    for dept, (hour, fn_path) in DEPT_SCHEDULE.items():
        tasks.append(asyncio.create_task(_dept_scheduler(dept, hour, fn_path)))

    # Urgent scanner (every 5 min for missed calls, failed payments, negative reviews)
    tasks.append(asyncio.create_task(_urgent_scanner()))

    # CEO standup
    tasks.append(asyncio.create_task(_ceo_standup_scheduler()))

    # Heartbeat
    tasks.append(asyncio.create_task(_heartbeat_scheduler()))

    print(f"[scheduler] ✅ {len(tasks)} autonomous tasks started")
    return tasks
