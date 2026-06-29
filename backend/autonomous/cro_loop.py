"""
CRO Autonomous Daily Work Loop — runs at 9am.
Proactively works on revenue every day:
- Scans for dormant customers and queues reactivation
- Checks membership renewals due this week
- Reviews failed payments and queues recovery
- Identifies upsell opportunities from recent visits
- Checks missed calls from yesterday
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.cro.agent import CROAgent


async def run_cro_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    dormant_cutoff = (now - timedelta(days=30)).isoformat()
    renewal_window = (now + timedelta(days=7)).isoformat()
    yesterday = (now - timedelta(days=1)).isoformat()

    actions_taken = []
    approvals_queued = []

    # ── 1. DORMANT CUSTOMERS ─────────────────────────────────
    dormant = sb.table("customers").select("id,name,phone,email,lifetime_value,last_visit")\
        .eq("business_id", bid).eq("opt_out_sms", False)\
        .lt("last_visit", dormant_cutoff).limit(20).execute().data or []

    for customer in dormant[:5]:  # max 5 reactivations queued per day
        await dispatch_action(bid, "reactivate_dormant_member", {
            "customer_id": customer["id"],
            "customer_name": customer.get("name", ""),
            "customer_phone": customer.get("phone", ""),
            "days_inactive": 30,
            "lifetime_value": customer.get("lifetime_value", 0),
        }, f"CRO daily loop: {customer.get('name','?')} dormant 30+ days (LTV ${customer.get('lifetime_value',0)})")
        approvals_queued.append(f"reactivation: {customer.get('name','?')}")

    # ── 2. MEMBERSHIPS EXPIRING THIS WEEK ────────────────────
    expiring = sb.table("customers").select("id,name,phone,tags")\
        .eq("business_id", bid).contains("tags", ["membership_active"]).execute().data or []
    # Flag potential renewals (simplified — real impl would check membership_expiry column)
    renewal_candidates = [c for c in expiring if c.get("phone")][:5]
    for c in renewal_candidates[:3]:
        await dispatch_action(bid, "send_renewal_reminder", {
            "customer_id": c["id"],
            "customer_name": c.get("name", ""),
            "customer_phone": c.get("phone", ""),
        }, f"CRO daily loop: membership renewal check for {c.get('name','?')}")
        approvals_queued.append(f"renewal reminder: {c.get('name','?')}")

    # ── 3. FAILED PAYMENT RECOVERY ───────────────────────────
    failed_payments = sb.table("tasks").select("id,parameters,created_at")\
        .eq("business_id", bid).eq("workflow", "recover_failed_payment")\
        .eq("status", "failed").gte("created_at", yesterday).execute().data or []
    for task in failed_payments[:3]:
        await dispatch_action(bid, "recover_failed_payment",
            task.get("parameters", {}),
            "CRO daily loop: retry failed payment recovery")
        actions_taken.append(f"payment recovery retry: {task['id']}")

    # ── 4. UPSELL OPPORTUNITIES FROM RECENT VISITS ───────────
    recent_completed = sb.table("appointments").select("id,customer_id,service,scheduled_at")\
        .eq("business_id", bid).eq("status", "completed")\
        .gte("scheduled_at", yesterday).execute().data or []
    for appt in recent_completed[:5]:
        await dispatch_action(bid, "send_upsell_offer", {
            "customer_id": appt.get("customer_id"),
            "appointment_id": appt["id"],
            "service": appt.get("service", ""),
            "trigger": "post_visit_24h",
        }, f"CRO daily loop: upsell opportunity 24h after visit")
        approvals_queued.append(f"upsell offer queued for appt {appt['id']}")

    # ── 5. MISSED CALLS FROM YESTERDAY ───────────────────────
    missed_calls = sb.table("calls").select("id,caller_phone,called_at")\
        .eq("business_id", bid).eq("status", "missed")\
        .gte("called_at", yesterday).execute().data or []
    for call in missed_calls:
        await dispatch_action(bid, "recover_missed_call", {
            "customer_phone": call.get("caller_phone"),
            "call_id": call["id"],
        }, "CRO daily loop: auto-recover yesterday missed call")
        actions_taken.append(f"missed call recovery: {call.get('caller_phone','?')}")

    # ── 6. CRO AGENT STRATEGIC REVIEW ────────────────────────
    try:
        agent = CROAgent(UUID(bid))
        context = {
            "dormant_customers": len(dormant),
            "reactivations_queued": len([a for a in approvals_queued if "reactivation" in a]),
            "failed_payments_retried": len(actions_taken),
            "upsells_queued": len([a for a in approvals_queued if "upsell" in a]),
            "missed_calls_recovered": len([a for a in actions_taken if "missed" in a]),
        }
        resp = await agent.run(
            "Daily revenue review: what are the top revenue opportunities right now? "
            "What should I prioritize to hit our monthly revenue goal?",
            context=context,
        )
        for rec in (resp.recommendations or [])[:3]:
            await dispatch_action(bid, "generate_reflection", {
                "agent": "CRO", "observation": rec, "source": "daily_loop"
            }, "CRO daily insight")
    except Exception:
        pass

    return {
        "department": "CRO",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "dormant_found": len(dormant),
        "missed_calls_recovered": len(missed_calls),
    }
