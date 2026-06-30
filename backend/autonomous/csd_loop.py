"""
CSD (Customer Success Director) Autonomous Daily Work Loop — runs at 3pm.
Proactively manages customer health every day:
- Reviews negative reviews/sentiment from last 24h
- Identifies churn-risk customers (tagged churn_risk)
- Queues satisfaction surveys for yesterday's visits
- Sends loyalty rewards to VIP customers
- Checks rebooking rate and queues reminders
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.customer_success.agent import CustomerSuccessAgent


async def run_csd_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    # Only run managers this business has enabled.
    from backend.engines.business_blueprint import is_manager_enabled
    try:
        _biz = sb.table("businesses").select("config").eq("id", bid).limit(1).execute().data
        config = (_biz[0].get("config") if _biz else {}) or {}
    except Exception:
        config = {}
    success_on = is_manager_enabled(config, "csd", "customer_success")
    loyalty_on = is_manager_enabled(config, "csd", "loyalty")
    reputation_on = is_manager_enabled(config, "csd", "reputation")

    actions_taken = []
    approvals_queued = []

    # ── 0. INGEST REVIEWS (Google/Yelp/FB) before acting on reputation ──
    try:
        from backend.integrations.reputation_monitor import ingest_reviews
        rep = await ingest_reviews(bid) if reputation_on else {}
        if rep.get("stored"):
            actions_taken.append(f"ingested {rep['stored']} reviews ({rep.get('negatives',0)} negative)")
    except Exception:
        pass

    # ── 1. NEGATIVE REVIEWS ──────────────────────────────────
    neg_calls = sb.table("calls").select("id,customer_id,sentiment,summary")\
        .eq("business_id", bid).eq("sentiment", "negative")\
        .gte("called_at", yesterday_start).execute().data or []
    for call in (neg_calls[:5] if success_on else []):
        await dispatch_action(bid, "handle_complaint", {
            "customer_id": call.get("customer_id"),
            "call_id": call["id"],
            "summary": call.get("summary", ""),
        }, "CSD daily loop: negative call sentiment from yesterday")
        approvals_queued.append(f"complaint follow-up: call {call['id']}")

    # Cross-dept: if multiple negatives, flag reputation risk to CEO
    if reputation_on and len(neg_calls) >= 3:
        try:
            from backend.events.inter_dept import csd_notify_ceo_reputation_risk
            await csd_notify_ceo_reputation_risk(bid, len(neg_calls), 2.0)
            actions_taken.append(f"alerted CEO: {len(neg_calls)} negative interactions")
        except Exception:
            pass

    # ── 2. CHURN RISK CUSTOMERS ──────────────────────────────
    churn_risk = sb.table("customers").select("id,name,phone,tags,lifetime_value")\
        .eq("business_id", bid).eq("opt_out_sms", False)\
        .contains("tags", ["churn_risk"]).limit(10).execute().data or []
    for c in (churn_risk[:5] if success_on else []):
        await dispatch_action(bid, "send_rebooking_reminder", {
            "customer_id": c["id"],
            "customer_name": c.get("name", ""),
            "customer_phone": c.get("phone", ""),
            "reason": "churn_risk_outreach",
        }, f"CSD daily loop: churn risk outreach to {c.get('name','?')}")
        approvals_queued.append(f"churn risk outreach: {c.get('name','?')}")

    # ── 3. SATISFACTION SURVEYS FOR YESTERDAY'S VISITS ───────
    completed_yesterday = sb.table("appointments").select("id,customer_id")\
        .eq("business_id", bid).eq("status", "completed")\
        .gte("scheduled_at", yesterday_start).execute().data or []
    for appt in (completed_yesterday[:10] if success_on else []):
        await dispatch_action(bid, "send_satisfaction_survey", {
            "customer_id": appt.get("customer_id"),
            "appointment_id": appt["id"],
        }, "CSD daily loop: post-visit satisfaction survey")
        actions_taken.append(f"survey queued for appt {appt['id']}")

    # ── 4. LOYALTY REWARDS FOR VIP CUSTOMERS ─────────────────
    vip_customers = sb.table("customers").select("id,name,phone,lifetime_value")\
        .eq("business_id", bid).gt("lifetime_value", 1000)\
        .eq("opt_out_sms", False).limit(5).execute().data or []
    for c in (vip_customers[:3] if loyalty_on else []):
        # Check if reward sent in last 30 days
        recent_reward = sb.table("tasks").select("id")\
            .eq("business_id", bid).eq("workflow", "send_loyalty_reward")\
            .eq("parameters->customer_id", c["id"])\
            .gte("created_at", (now - timedelta(days=30)).isoformat()).execute().data or []
        if not recent_reward:
            await dispatch_action(bid, "send_loyalty_reward", {
                "customer_id": c["id"],
                "customer_name": c.get("name", ""),
                "lifetime_value": c.get("lifetime_value", 0),
            }, f"CSD daily loop: VIP loyalty reward for {c.get('name','?')} (LTV ${c.get('lifetime_value',0)})")
            approvals_queued.append(f"loyalty reward: {c.get('name','?')}")

    # ── 5. GOOGLE REVIEW REQUESTS ────────────────────────────
    completed_no_review = sb.table("appointments").select("id,customer_id")\
        .eq("business_id", bid).eq("status", "completed")\
        .gte("scheduled_at", (now - timedelta(days=2)).isoformat())\
        .lte("scheduled_at", yesterday_start).execute().data or []
    for appt in (completed_no_review[:5] if reputation_on else []):
        await dispatch_action(bid, "request_google_review", {
            "customer_id": appt.get("customer_id"),
            "appointment_id": appt["id"],
        }, "CSD daily loop: Google review request for completed visit")
        actions_taken.append(f"review request queued: appt {appt['id']}")

    # ── 6. CSD AGENT STRATEGIC REVIEW ────────────────────────
    try:
        agent = CustomerSuccessAgent(UUID(bid))
        context = {
            "negative_calls_24h": len(neg_calls),
            "churn_risk_customers": len(churn_risk),
            "surveys_queued": len([a for a in actions_taken if "survey" in a]),
            "vip_rewards_queued": len([a for a in approvals_queued if "loyalty" in a]),
        }
        resp = await agent.run(
            "Daily customer success review: what is the health of our customer relationships today? "
            "What should I do to improve satisfaction and prevent churn?",
            context=context,
        )
        for rec in (resp.recommendations or [])[:3]:
            await dispatch_action(bid, "generate_reflection", {
                "agent": "CSD", "observation": rec, "source": "daily_loop"
            }, "CSD daily insight")
    except Exception:
        pass

    return {
        "department": "CSD",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "churn_risk_found": len(churn_risk),
        "surveys_sent": len([a for a in actions_taken if "survey" in a]),
    }
