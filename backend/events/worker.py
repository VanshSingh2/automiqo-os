"""
Event Worker — background loop processing events from Redis queue.
Runs alongside task worker in main.py lifespan.
"""
import json
import asyncio
from datetime import datetime, timezone, timedelta
from backend.events.router import get_handlers
from backend.events.handlers import (
    handle_coo, handle_cro, handle_cmo,
    handle_cfo, handle_csd, handle_cto, handle_learning, handle_ceo,
)

DEPT_HANDLERS = {
    "coo": handle_coo,
    "cro": handle_cro,
    "cmo": handle_cmo,
    "cfo": handle_cfo,
    "csd": handle_csd,
    "cto": handle_cto,
    "learning": handle_learning,
    "ceo": handle_ceo,
}


async def _handle_internal_alert(business_id: str, event_type: str, payload: dict) -> None:
    """Route internal dept-to-dept alerts to the right handler."""
    dept_map = {
        "internal.coo_alert": "coo",
        "internal.cro_alert": "cro",
        "internal.cmo_alert": "cmo",
        "internal.cfo_alert": "cfo",
        "internal.cto_alert": "cto",
        "internal.csd_alert": "csd",
        "internal.learning_alert": "learning",
        "internal.ceo_alert": "ceo",
        "internal.alert": "ceo",
    }
    dept = dept_map.get(event_type)
    if dept and dept in DEPT_HANDLERS:
        # Wrap as a synthetic event the handler understands
        await DEPT_HANDLERS[dept](business_id, event_type, {
            **payload,
            "_internal": True,
            "_from": payload.get("from", "system"),
        })


async def _handle_dept_work_trigger(business_id: str, event_type: str, payload: dict) -> None:
    """Fire the autonomous daily work loop for the triggered department."""
    dept = event_type.replace("dept.work.", "")
    loop_map = {
        "coo": "backend.autonomous.coo_loop.run_coo_daily_loop",
        "cmo": "backend.autonomous.cmo_loop.run_cmo_daily_loop",
        "cro": "backend.autonomous.cro_loop.run_cro_daily_loop",
        "cfo": "backend.autonomous.cfo_loop.run_cfo_daily_loop",
        "cto": "backend.autonomous.cto_loop.run_cto_daily_loop",
        "csd": "backend.autonomous.csd_loop.run_csd_daily_loop",
        "learning": "backend.autonomous.learning_loop.run_learning_daily_loop",
    }
    fn_path = loop_map.get(dept)
    if not fn_path:
        return
    module_path, fn_name = fn_path.rsplit(".", 1)
    try:
        import importlib
        module = importlib.import_module(module_path)
        fn = getattr(module, fn_name)
        result = await fn(business_id)
        print(f"[{dept.upper()} loop] {result.get('actions_taken',0)} actions, {result.get('approvals_queued',0)} queued")
    except Exception as e:
        print(f"[{dept.upper()} loop] Error: {e}")


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

            # Internal dept-to-dept alerts
            if event_type.startswith("internal."):
                await _handle_internal_alert(business_id, event_type, payload)
                continue

            # Autonomous dept work triggers (from scheduler)
            if event_type.startswith("dept.work."):
                await _handle_dept_work_trigger(business_id, event_type, payload)
                continue

            # Standard fan-out
            handlers = get_handlers(event_type)
            if not handlers:
                continue

            tasks = [
                DEPT_HANDLERS[dept](business_id, event_type, payload)
                for dept in handlers if dept in DEPT_HANDLERS
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Mark event processed
            try:
                get_supabase().table("events").update(
                    {"listeners_notified": handlers}
                ).eq("id", event_id).execute()
            except Exception:
                pass

        except Exception as e:
            print(f"[event_worker] Error: {e}")
            await asyncio.sleep(1)


async def run_hourly_heartbeat(business_id: str):
    """
    Comprehensive hourly scan — all depts check for pending work.
    Fired every 60 minutes by the autonomous scheduler.
    """
    from backend.events.bus import publish, E
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    # ── COO: appointments needing reminders ──────────────────
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

    # ── CRO: dormant customers ────────────────────────────────
    dormant_cutoff = (now - timedelta(days=30)).isoformat()
    dormant = sb.table("customers").select("id,name,phone") \
        .eq("business_id", business_id).eq("opt_out_sms", False) \
        .lt("last_visit", dormant_cutoff).limit(5).execute().data or []
    for customer in dormant:
        await publish(business_id, E.CUSTOMER_DORMANT, {
            "customer_id": customer["id"],
            "customer_name": customer.get("name", ""),
            "customer_phone": customer.get("phone", ""),
            "days_inactive": 30,
        }, source="heartbeat")

    # ── CRO: missed calls in last hour ───────────────────────
    # NOTE: missed calls are also caught by urgent_scanner every 5 min.
    # Heartbeat catches any that the urgent scanner or webhook missed.
    hour_ago = (now - timedelta(hours=1)).isoformat()
    missed = sb.table("calls").select("id,caller_phone") \
        .eq("business_id", business_id).eq("status", "missed") \
        .gte("called_at", hour_ago).execute().data or []
    for call in missed:
        await publish(business_id, E.CALL_MISSED, {
            "customer_phone": call.get("caller_phone"),
            "call_id": call["id"],
        }, source="heartbeat")

    # ── CTO: failed workflows in last hour ───────────────────
    failed = sb.table("tasks").select("id,workflow,error") \
        .eq("business_id", business_id).eq("status", "failed") \
        .gte("created_at", hour_ago).execute().data or []
    for task in failed:
        await publish(business_id, E.WORKFLOW_FAILED, {
            "task_id": task["id"],
            "workflow": task["workflow"],
            "error": task.get("error", ""),
        }, source="heartbeat")

    # ── Nurture sequences: run all due steps ─────────────────
    try:
        from backend.integrations.nurture_sequences import run_due_sequences
        await run_due_sequences(business_id)
    except Exception:
        pass

    # ── Opportunity Engine: surface top opportunities ─────────
    try:
        from backend.engines.opportunity_engine import opportunity_engine
        opps = await opportunity_engine.scan(business_id)
        if opps:
            top = opps[0]
            from backend.events.bus import publish
            await publish(business_id, "opportunity.detected", {
                "type": top.get("type"),
                "title": top.get("title"),
                "potential_value": top.get("potential_value"),
                "action": top.get("action"),
                "priority": top.get("priority"),
            }, source="heartbeat")
    except Exception:
        pass

    # ── CSD: churn risk customers ────────────────────────────
    churn = sb.table("customers").select("id,name,phone") \
        .eq("business_id", business_id).contains("tags", ["churn_risk"]) \
        .eq("opt_out_sms", False).limit(5).execute().data or []
    for c in churn:
        await publish(business_id, E.CUSTOMER_CHURN_RISK, {
            "customer_id": c["id"],
            "customer_name": c.get("name", ""),
        }, source="heartbeat")

    # ── CFO: payment failures in last hour ───────────────────
    failed_payments = sb.table("tasks").select("id,parameters") \
        .eq("business_id", business_id).eq("workflow", "recover_failed_payment") \
        .eq("status", "failed").gte("created_at", hour_ago).execute().data or []
    for task in failed_payments:
        await publish(business_id, E.PAYMENT_FAILED,
            task.get("parameters", {}), source="heartbeat")

    return {
        "reminders_due": len(appts),
        "dormant_customers": len(dormant),
        "missed_calls": len(missed),
        "failed_workflows": len(failed),
        "churn_risk": len(churn),
        "payment_failures": len(failed_payments),
    }
