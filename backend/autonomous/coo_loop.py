"""
COO Autonomous Daily Work Loop — runs at 6am.
Proactively manages operations without waiting for events:
- Reviews today's appointments and staff coverage
- Checks inventory reorder alerts
- Flags compliance gaps
- Logs no-shows from yesterday
- Queues reminders for today's bookings
"""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.coo.agent import COOAgent


async def run_coo_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_end = now.replace(hour=23, minute=59, second=59).isoformat()
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat()

    actions_taken = []
    approvals_queued = []

    # ── 1. TODAY'S APPOINTMENTS ──────────────────────────────
    appts = sb.table("appointments").select(
        "id,customer_id,staff_id,service,scheduled_at,status,reminder_sent"
    ).eq("business_id", bid).gte("scheduled_at", today_start).lte("scheduled_at", today_end).execute().data or []

    # Queue reminders for confirmed appointments without reminder
    for appt in appts:
        if appt.get("status") == "confirmed" and not appt.get("reminder_sent"):
            await dispatch_action(bid, "send_reminder_24h", {
                "appointment_id": appt["id"],
                "customer_id": appt.get("customer_id"),
                "scheduled_at": appt.get("scheduled_at"),
            }, "COO daily loop: reminder for today's booking")
            actions_taken.append(f"reminder queued for appt {appt['id']}")

    # ── 2. YESTERDAY'S NO-SHOWS ──────────────────────────────
    no_shows = sb.table("appointments").select("id,customer_id,service").eq("business_id", bid)\
        .eq("status", "scheduled").gte("scheduled_at", yesterday_start).lt("scheduled_at", today_start).execute().data or []
    for ns in no_shows:
        await dispatch_action(bid, "log_no_show", {
            "appointment_id": ns["id"],
            "customer_id": ns.get("customer_id"),
        }, "COO daily loop: auto-log yesterday no-show")
        actions_taken.append(f"logged no-show {ns['id']}")

    # ── 3. INVENTORY REORDER CHECK ───────────────────────────
    low_stock = sb.table("inventory").select("id,product_name,quantity,reorder_threshold")\
        .eq("business_id", bid).execute().data or []
    for item in low_stock:
        qty = item.get("quantity", 0) or 0
        threshold = item.get("reorder_threshold", 0) or 0
        if qty <= threshold:
            await dispatch_action(bid, "send_inventory_reorder_alert", {
                "product_name": item["product_name"],
                "current_quantity": qty,
                "reorder_threshold": threshold,
            }, f"COO daily loop: {item['product_name']} at {qty} units (threshold {threshold})")
            approvals_queued.append(f"reorder alert: {item['product_name']}")

    # ── 4. STAFF COVERAGE CHECK ──────────────────────────────
    staff = sb.table("staff").select("id,name,role").eq("business_id", bid).eq("active", True).execute().data or []
    if len(appts) > 0 and len(staff) == 0:
        await dispatch_action(bid, "send_shift_swap_request", {
            "reason": "No active staff found but appointments exist today",
            "appointment_count": len(appts),
        }, "COO daily loop: no staff coverage for today")
        approvals_queued.append("staff coverage alert")

    # ── 5. ASK COO AGENT FOR ANYTHING ELSE ──────────────────
    try:
        agent = COOAgent(UUID(bid))
        context = {
            "todays_appointments": len(appts),
            "no_shows_yesterday": len(no_shows),
            "low_stock_items": len([i for i in low_stock if (i.get("quantity") or 0) <= (i.get("reorder_threshold") or 0)]),
            "active_staff": len(staff),
            "actions_auto_taken": actions_taken,
        }
        resp = await agent.run(
            "Daily autonomous review: based on today's data, what else needs attention right now? "
            "List specific actions with workflow names and parameters.",
            context=context,
        )
        # Parse and dispatch any additional recommendations
        for rec in (resp.recommendations or [])[:3]:
            await dispatch_action(bid, "generate_reflection", {
                "agent": "COO", "observation": rec, "source": "daily_loop"
            }, "COO daily insight")
    except Exception:
        pass

    return {
        "department": "COO",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "appointments_today": len(appts),
        "no_shows_logged": len(no_shows),
    }
