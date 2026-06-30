"""
Agent Chat — the human-readable layer on top of the OS.

Two surfaces:

1. TEAM CHAT  (channel='team')
   A group chat where the CEO, department heads, and managers talk to each
   other like a real team — "COO → CMO: no-show rate is up, can you prep a
   re-engagement campaign?". Stored in the `agent_messages` table.

2. BACKSTAGE FEED  (derived, not stored here)
   Every backend action translated into a plain-English line — "Sent a 24h
   reminder to a customer", "Queued an inventory reorder for your approval".
   Built on read from the existing `events` table, so it costs no extra writes.

All writes are best-effort: if Supabase/the table is missing, chat simply
no-ops and never breaks the core agent flow.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


# Friendly display names + roles for each agent key
AGENT_PROFILE: dict[str, tuple[str, str]] = {
    "ceo":      ("CEO", "executive"),
    "coo":      ("COO", "department"),
    "cmo":      ("CMO", "department"),
    "cro":      ("CRO", "department"),
    "cfo":      ("CFO", "department"),
    "cto":      ("CTO", "department"),
    "csd":      ("Customer Success", "department"),
    "learning": ("Learning Lead", "department"),
    "owner":    ("Owner", "owner"),
    "system":   ("System", "system"),
    "scheduler":("Scheduler", "system"),
    "urgent_scanner": ("Urgent Scanner", "system"),
}


def agent_display(key: str) -> tuple[str, str]:
    """Return (display_name, role) for an agent key; falls back gracefully."""
    k = (key or "system").lower()
    if k in AGENT_PROFILE:
        return AGENT_PROFILE[k]
    # Title-case unknown keys (e.g. a manager name)
    return (key.replace("_", " ").title(), "manager")


async def post_team_message(
    business_id: str,
    from_agent: str,
    message: str,
    to_agent: str = "team",
    category: str = "update",
    urgency: str = "normal",
    related_event_id: Optional[str] = None,
    channel: str = "team",
) -> Optional[str]:
    """Post a message into the team group chat (or a DM). Best-effort, never raises."""
    try:
        from backend.memory.supabase_client import get_supabase
        name, role = agent_display(from_agent)
        sb = get_supabase()
        row = {
            "business_id": business_id,
            "channel": channel,
            "from_agent": name,
            "from_role": role,
            "to_agent": to_agent,
            "message": message,
            "category": category,
            "urgency": urgency,
        }
        if related_event_id:
            row["related_event_id"] = related_event_id
        res = sb.table("agent_messages").insert(row).execute()
        return res.data[0]["id"] if res.data else None
    except Exception:
        return None


def post_team_message_sync(business_id: str, from_agent: str, message: str, **kw) -> None:
    """Sync wrapper for non-async contexts."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(post_team_message(business_id, from_agent, message, **kw))
        else:
            loop.run_until_complete(post_team_message(business_id, from_agent, message, **kw))
    except Exception:
        pass


# ── Backstage translation: event row -> plain-English line ─────────────────
# Map event types to a short, human template. {who} is the actor.
_EVENT_TEMPLATES: dict[str, str] = {
    "lead.discovered":      "Found a new potential lead",
    "lead.contacted":       "Reached out to a lead",
    "lead.replied":         "A lead replied to outreach",
    "lead.booked":          "A lead booked an appointment",
    "appointment.booked":   "A new appointment was booked",
    "appointment.cancelled":"An appointment was cancelled",
    "appointment.completed":"An appointment was completed",
    "appointment.no_show":  "A customer didn't show up — flagged for follow-up",
    "appointment.reminder_due": "An appointment reminder is due",
    "customer.dormant":     "A customer has gone quiet (30+ days) — added to win-back",
    "customer.churn_risk":  "A customer looks at risk of leaving",
    "customer.vip_threshold":"A customer reached VIP status",
    "sms.received":         "Received an SMS from a customer",
    "call.missed":          "A call was missed — recovering it now",
    "call.completed":       "A call was completed",
    "review.received":      "A new review came in",
    "review.negative":      "A negative review/feedback came in — responding",
    "payment.failed":       "A payment failed — attempting recovery",
    "membership.expiring":  "A membership is about to expire",
    "upsell.opportunity":   "Spotted an upsell opportunity",
    "referral.converted":   "A referral converted into a customer",
    "sequence.enrolled":    "A customer was enrolled in a nurture sequence",
    "sequence.step_due":    "A nurture step is due to send",
    "sequence.completed":   "A nurture sequence finished",
    "workflow.failed":      "An automation failed — flagged to the CTO",
    "workflow.completed":   "An automation finished successfully",
    "daily.standup":        "The CEO kicked off the daily standup",
    "hourly.heartbeat":     "Hourly check — scanning for anything urgent",
}

# internal.* alerts are dept-to-dept; render them with the message in payload.
_DEPT_FROM_EVENT = {
    "internal.coo_alert": "COO", "internal.cmo_alert": "CMO",
    "internal.cro_alert": "CRO", "internal.cfo_alert": "CFO",
    "internal.cto_alert": "CTO", "internal.csd_alert": "Customer Success",
    "internal.learning_alert": "Learning Lead", "internal.alert": "Team",
}


def translate_event(event: dict) -> dict:
    """
    Turn a raw `events` row into a friendly backstage line.

    Returns: {who, action, urgency, event_type, at}
    """
    etype = event.get("event_type", "")
    payload = event.get("payload") or {}
    source = payload.get("source") or event.get("source") or "system"
    urgency = payload.get("urgency", "normal")
    at = event.get("created_at") or event.get("published_at")

    # Department-to-department alert: surface the actual message
    if etype.startswith("internal."):
        who, _ = agent_display(payload.get("from_dept", source))
        msg = payload.get("message") or _DEPT_FROM_EVENT.get(etype, "Coordinated with the team")
        return {"who": who, "action": msg, "urgency": urgency, "event_type": etype, "at": at}

    if etype.startswith("dept.work."):
        dept = etype.split(".")[-1]
        who, _ = agent_display(dept)
        return {"who": who, "action": "Started the daily work routine",
                "urgency": urgency, "event_type": etype, "at": at}

    who, _ = agent_display(source)
    action = _EVENT_TEMPLATES.get(etype, etype.replace(".", " ").replace("_", " ").capitalize())
    return {"who": who, "action": action, "urgency": urgency, "event_type": etype, "at": at}
