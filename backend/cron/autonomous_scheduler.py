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
CEO_STANDUP_HOUR = 7   # CEO morning standup


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


async def _run_dept_loop(dept: str, fn_path: str, business_id: str):
    """Import and run a dept loop function."""
    module_path, fn_name = fn_path.rsplit(".", 1)
    try:
        import importlib
        module = importlib.import_module(module_path)
        fn = getattr(module, fn_name)
        result = await fn(business_id)
        print(f"[scheduler][{dept.upper()}][{business_id[:8]}] done — "
              f"{result.get('actions_taken',0)} actions, {result.get('approvals_queued',0)} queued for approval")
    except Exception as e:
        print(f"[scheduler][{dept.upper()}] Error: {e}")


async def _dept_scheduler(dept: str, target_hour_est: int, fn_path: str):
    """Per-department scheduler loop — fires once per day at the configured hour."""
    print(f"[scheduler] {dept.upper()} scheduled at {target_hour_est}:00 EST")
    while True:
        now = datetime.now(timezone.utc)
        wait = _seconds_until_next_hour(target_hour_est, now)
        await asyncio.sleep(wait)

        businesses = await _get_all_active_businesses()
        if not businesses:
            continue

        print(f"[scheduler] ⏰ {dept.upper()} daily loop firing for {len(businesses)} business(es)")
        await asyncio.gather(
            *[_run_dept_loop(dept, fn_path, bid) for bid in businesses],
            return_exceptions=True,
        )

        # Also publish dept.work event for any event-driven subscribers
        for bid in businesses:
            await publish(bid, f"dept.work.{dept}", {"triggered_by": "scheduler"}, source="scheduler")

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

        await asyncio.sleep(23 * 3600)


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

    # CEO standup
    tasks.append(asyncio.create_task(_ceo_standup_scheduler()))

    # Heartbeat
    tasks.append(asyncio.create_task(_heartbeat_scheduler()))

    print(f"[scheduler] ✅ {len(tasks)} autonomous tasks started")
    return tasks
