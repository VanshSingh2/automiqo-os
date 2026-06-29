"""
Event Bus — publishes business events to Redis queue + Supabase log.
Every significant action in the OS fires an event here.
All dept agents listen and react autonomously.
"""
import json
import os
from datetime import datetime, timezone
from uuid import UUID


# ── Event Types ───────────────────────────────────────────────
class E:
    # Lead lifecycle
    LEAD_DISCOVERED     = "lead.discovered"
    LEAD_CONTACTED      = "lead.contacted"
    LEAD_REPLIED        = "lead.replied"
    LEAD_BOOKED         = "lead.booked"

    # Appointment lifecycle
    APPT_BOOKED         = "appointment.booked"
    APPT_CANCELLED      = "appointment.cancelled"
    APPT_COMPLETED      = "appointment.completed"
    APPT_NO_SHOW        = "appointment.no_show"
    APPT_REMINDER_DUE   = "appointment.reminder_due"

    # Customer lifecycle
    CUSTOMER_DORMANT    = "customer.dormant"        # 30+ days no visit
    CUSTOMER_CHURN_RISK = "customer.churn_risk"     # tagged churn_risk
    CUSTOMER_VIP        = "customer.vip_threshold"  # hit VIP spend

    # Communication
    SMS_RECEIVED        = "sms.received"
    CALL_MISSED         = "call.missed"
    CALL_COMPLETED      = "call.completed"
    REVIEW_RECEIVED     = "review.received"
    REVIEW_NEGATIVE     = "review.negative"

    # Revenue
    PAYMENT_FAILED      = "payment.failed"
    MEMBERSHIP_EXPIRING = "membership.expiring"
    UPSELL_OPPORTUNITY  = "upsell.opportunity"
    REFERRAL_CONVERTED  = "referral.converted"

    # Nurture sequences
    SEQUENCE_ENROLLED   = "sequence.enrolled"
    SEQUENCE_STEP_DUE   = "sequence.step_due"
    SEQUENCE_COMPLETED  = "sequence.completed"

    # Platform
    WORKFLOW_FAILED     = "workflow.failed"
    WORKFLOW_COMPLETED  = "workflow.completed"

    # Scheduled intelligence
    DAILY_STANDUP       = "daily.standup"
    HOURLY_HEARTBEAT    = "hourly.heartbeat"


async def publish(
    business_id: str,
    event_type: str,
    payload: dict,
    source: str = "system",
) -> str:
    """
    Publish an event to the bus.
    Writes to Supabase events table + pushes to Redis for immediate processing.

    Returns the event ID.
    """
    from backend.memory.supabase_client import get_supabase

    # Store in Supabase for audit trail
    sb = get_supabase()
    result = sb.table("events").insert({
        "business_id": business_id,
        "event_type": event_type,
        "payload": {**payload, "source": source},
        "listeners_notified": [],
    }).execute()
    event_id = result.data[0]["id"] if result.data else "unknown"

    # Push to Redis for immediate async processing
    try:
        from backend.dispatcher.queue import get_redis
        r = await get_redis()
        event_data = {
            "event_id": event_id,
            "event_type": event_type,
            "business_id": business_id,
            "payload": payload,
            "source": source,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        await r.rpush("events:queue", json.dumps(event_data))
    except Exception:
        pass  # Redis optional — Supabase is the source of truth

    return event_id


def publish_sync(business_id: str, event_type: str, payload: dict, source: str = "system") -> None:
    """Sync version for use in non-async contexts (n8n webhooks, etc.)"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(publish(business_id, event_type, payload, source))
        else:
            loop.run_until_complete(publish(business_id, event_type, payload, source))
    except Exception:
        pass
