"""
Event Worker — background loop that processes events from Redis queue.
Runs alongside the task worker in main.py lifespan.
"""
import json
import asyncio
from backend.events.router import get_handlers
from backend.events.handlers import (
    handle_coo, handle_cro, handle_cmo,
    handle_csd, handle_cto, handle_learning, handle_ceo,
)

DEPT_HANDLERS = {
    "coo": handle_coo,
    "cro": handle_cro,
    "cmo": handle_cmo,
    "csd": handle_csd,
    "cto": handle_cto,
    "learning": handle_learning,
    "ceo": handle_ceo,
}


async def event_worker_loop():
    """Background loop: read events from Redis, fan-out to dept handlers."""
    from backend.dispatcher.queue import get_redis
    from backend.memory.supabase_client import get_supabase
    print("✅ Event worker started")
    r = await get_redis()

    while True:
        try:
            item = await r.blpop(["events:queue"], timeout=10)
            if not item:
                continue
            _, raw = item
            event = json.loads(raw)

            event_type = event.get("event_type", "")
            business_id = event.get("business_id", "")
            payload = event.get("payload", {})
            event_id = event.get("event_id", "")

            handlers = get_handlers(event_type)
            if not handlers:
                continue

            # Fan-out to all subscribed dept handlers in parallel
            tasks = []
            for dept in handlers:
                if dept in DEPT_HANDLERS:
                    tasks.append(DEPT_HANDLERS[dept](business_id, event_type, payload))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Mark event as processed
                try:
                    sb = get_supabase()
                    sb.table("events").update({
                        "listeners_notified": handlers,
                    }).eq("id", event_id).execute()
                except Exception:
                    pass

        except Exception as e:
            print(f"[event_worker] Error: {e}")
            await asyncio.sleep(1)


async def run_hourly_heartbeat(business_id: str):
    """
    Hourly check — each dept agent scans for pending work without waiting for events.
    COO: any reminders due? CRO: any dormant customers? etc.
    """
    from backend.events.bus import publish, E
    from backend.memory.supabase_client import get_supabase
    from datetime import datetime, timezone, timedelta

    sb = get_supabase()
    now = datetime.now(timezone.utc)

    # COO: check for appointments needing reminders in next 24h
    reminder_window = (now + timedelta(hours=24)).isoformat()
    appts = sb.table("appointments").select("id,customer_id,scheduled_at") \
        .eq("business_id", business_id).eq("status", "confirmed") \
        .eq("reminder_sent", False).lte("scheduled_at", reminder_window) \
        .execute().data or []
    for appt in appts:
        await publish(business_id, E.APPT_REMINDER_DUE, {
            "appointment_id": appt["id"],
            "customer_id": appt["customer_id"],
            "scheduled_at": appt["scheduled_at"],
        }, source="heartbeat")

    # CRO: check for dormant customers (30+ days no visit)
    dormant_cutoff = (now - timedelta(days=30)).isoformat()
    dormant = sb.table("customers").select("id,name,phone") \
        .eq("business_id", business_id).eq("opt_out_sms", False) \
        .lt("last_visit", dormant_cutoff).limit(10).execute().data or []
    for customer in dormant:
        await publish(business_id, E.CUSTOMER_DORMANT, {
            "customer_id": customer["id"],
            "customer_name": customer.get("name", ""),
            "customer_phone": customer.get("phone", ""),
            "days_inactive": 30,
        }, source="heartbeat")
