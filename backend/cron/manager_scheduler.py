"""
Manager Scheduler — keeps every manager on its own heartbeat.

Rather than spawning 32 timers, it round-robins: every few minutes the next
manager takes a short autonomous shift (see manager_pulse). With the default
180-minute cadence and 32 managers, one manager pulses roughly every 5-6
minutes, so there's almost always *someone* thinking — and each manager comes
around about 8 times a day.

Controls (env):
  MANAGER_AUTONOMY=false              -> turn the whole thing off
  MANAGER_PULSE_INTERVAL_MINUTES=180  -> how often each manager comes around
"""
import os
import asyncio
from backend.memory.supabase_client import get_supabase
from backend.autonomous.manager_pulse import all_manager_keys, run_manager_pulse


async def _get_active_business_ids() -> list[str]:
    try:
        sb = get_supabase()
        rows = sb.table("businesses").select("id").eq("active", True).execute().data or []
        return [str(r["id"]) for r in rows]
    except Exception as e:
        print(f"[manager_scheduler] could not fetch businesses: {e}")
        return []


async def _manager_pulse_loop():
    managers = all_manager_keys()
    interval_min = int(os.getenv("MANAGER_PULSE_INTERVAL_MINUTES", "180"))
    # Time between individual manager pulses so each manager comes around once
    # per interval. Floor at 30s to avoid hammering on tiny intervals.
    step = max(interval_min * 60 / max(len(managers), 1), 30)
    print(f"[manager_scheduler] {len(managers)} managers, one every ~{step/60:.1f} min "
          f"(each ~every {interval_min} min)")

    idx = 0
    while True:
        await asyncio.sleep(step)
        mkey = managers[idx % len(managers)]
        idx += 1
        businesses = await _get_active_business_ids()
        if not businesses:
            continue
        for bid in businesses:
            async def _pulse(b=bid, m=mkey):
                try:
                    res = await run_manager_pulse(b, m)
                    if res.get("thought") and not res.get("quiet") and not res.get("skipped"):
                        print(f"[manager_pulse][{b[:8]}][{m}] {res['thought'][:120]}")
                except Exception as e:
                    print(f"[manager_pulse][{m}] error: {e}")
            asyncio.create_task(_pulse())


async def start_manager_schedulers() -> list:
    """Launch manager autonomy. Returns tasks for lifespan cancellation."""
    if os.getenv("MANAGER_AUTONOMY", "true").lower() == "false":
        print("[manager_scheduler] MANAGER_AUTONOMY=false — managers run only under their dept heads")
        return []
    task = asyncio.create_task(_manager_pulse_loop())
    print("[manager_scheduler] ✅ manager autonomy started")
    return [task]
