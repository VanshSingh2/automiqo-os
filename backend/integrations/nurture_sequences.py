"""
Lead Nurturing Drip Sequences — multi-touch follow-up for leads.

Sequences:
  cold_lead:     Day 1 → Day 3 → Day 7 → Day 14
  warm_lead:     Day 1 → Day 2 → Day 5
  post_visit:    1h → 24h → 7 days
  no_show:       2h → 24h → 7 days (3-step recovery)
  win_back:      Day 1 → Day 7 → Day 30

Each step: check if they responded → if yes, stop → if no, send next message.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.dispatcher.dispatcher import dispatch
from shared.schemas import TaskRequest, TaskPriority


# ── Sequence definitions ──────────────────────────────────────────────────────

SEQUENCES = {
    "cold_lead": [
        {"delay_hours": 0,   "channel": "sms",   "template": "cold_intro"},
        {"delay_hours": 48,  "channel": "sms",   "template": "cold_followup_1"},
        {"delay_hours": 168, "channel": "sms",   "template": "cold_followup_2"},
        {"delay_hours": 336, "channel": "email",  "template": "cold_breakup"},
    ],
    "warm_lead": [
        {"delay_hours": 0,  "channel": "sms",   "template": "warm_intro"},
        {"delay_hours": 24, "channel": "sms",   "template": "warm_value"},
        {"delay_hours": 96, "channel": "sms",   "template": "warm_booking_push"},
    ],
    "post_visit": [
        {"delay_hours": 1,   "channel": "sms",   "template": "post_visit_checkin"},
        {"delay_hours": 24,  "channel": "sms",   "template": "post_visit_survey"},
        {"delay_hours": 168, "channel": "sms",   "template": "rebook_offer"},
    ],
    "no_show": [
        {"delay_hours": 2,   "channel": "sms",   "template": "no_show_reschedule"},
        {"delay_hours": 24,  "channel": "sms",   "template": "no_show_offer"},
        {"delay_hours": 168, "channel": "sms",   "template": "no_show_final"},
    ],
    "win_back": [
        {"delay_hours": 0,   "channel": "sms",   "template": "win_back_miss_you"},
        {"delay_hours": 168, "channel": "sms",   "template": "win_back_offer"},
        {"delay_hours": 720, "channel": "email",  "template": "win_back_final"},
    ],
}

MESSAGE_TEMPLATES = {
    # Cold lead
    "cold_intro": "Hi {name}! I saw your business {company} — we help {industry} businesses like yours automate bookings & customer follow-ups. Worth a quick chat? Reply YES and I'll share more.",
    "cold_followup_1": "Hey {name}, just following up! Many {industry} owners we work with were losing 30% of leads to missed calls. We fix that automatically. Interested? Reply YES",
    "cold_followup_2": "Hi {name} — last follow-up from me. We have a quick demo that shows exactly how {company} could look with AI handling your bookings & reminders. Want to see it? Reply DEMO",
    "cold_breakup": "Hi {name}, I won't keep reaching out — but if things change and you want to automate your {industry} business, I'm here. Just reply READY anytime. Best of luck!",
    # Warm lead
    "warm_intro": "Hi {name}! Thanks for your interest. We help {industry} businesses book more clients automatically — no extra work for you. When's a good time for a quick call?",
    "warm_value": "Hi {name}, quick question: how many calls/messages do you miss in a week? Most {industry} businesses miss 5-10. Our AI catches them all and books appointments 24/7. Want to see it?",
    "warm_booking_push": "Hi {name}! Ready to stop losing clients to missed calls? Book a free 15-min demo: {booking_url} — takes 2 mins. We'll show you exactly what's possible.",
    # Post-visit
    "post_visit_checkin": "Hi {name}! Hope your visit was great today 😊 Any questions about your treatment? We're here if you need us!",
    "post_visit_survey": "Hi {name}! How was your experience with us? Reply with a number 1-5 (5 = amazing!) — your feedback helps us improve.",
    "rebook_offer": "Hi {name}! It's been a week since your visit — ready to book your next appointment? Reply BOOK and we'll get you set up quickly!",
    # No-show
    "no_show_reschedule": "Hi {name}, we missed you today! No worries — life happens. Want to reschedule? Reply REBOOK and we'll find you a new time.",
    "no_show_offer": "Hi {name}, still thinking about rescheduling? We'd love to see you. Book here: {booking_url} — or reply and we'll handle it for you.",
    "no_show_final": "Hi {name}, last reminder about your missed appointment. We have openings this week — reply YES to claim one or we'll release the spot.",
    # Win-back
    "win_back_miss_you": "Hi {name}! It's been a while and we miss you 💙 As a valued client, here's 15% off your next visit. Reply COMEBACK to book.",
    "win_back_offer": "Hi {name}, your exclusive offer expires soon! 15% off + priority booking. Don't let it go to waste — reply BOOK or visit: {booking_url}",
    "win_back_final": "Hi {name}, final message from us. We'd love to have you back. If now's not the right time, no worries at all — we'll be here when you're ready!",
}


# ── Core functions ────────────────────────────────────────────────────────────

async def enroll_in_sequence(
    business_id: str,
    contact_id: str,
    contact_type: str,
    phone: str,
    email: str,
    sequence_name: str,
    context: dict = None,
) -> dict:
    """
    Enroll a lead/customer in a nurture sequence.
    Creates sequence_enrollments record + schedules step 0 immediately.

    Args:
        business_id:   Business ID
        contact_id:    Lead ID or Customer ID
        contact_type:  'lead' or 'customer'
        phone:         Contact phone
        email:         Contact email
        sequence_name: 'cold_lead' | 'warm_lead' | 'post_visit' | 'no_show' | 'win_back'
        context:       {name, company, industry, booking_url, service, ...}
    """
    if sequence_name not in SEQUENCES:
        return {"error": f"Unknown sequence: {sequence_name}"}

    sb = get_supabase()

    # Check not already enrolled and active
    existing = sb.table("sequence_enrollments").select("id,status")\
        .eq("business_id", business_id).eq("contact_id", contact_id)\
        .eq("sequence_name", sequence_name).eq("status", "active").execute().data
    if existing:
        return {"already_enrolled": True, "enrollment_id": existing[0]["id"]}

    # Create enrollment
    enrollment = sb.table("sequence_enrollments").insert({
        "business_id": business_id,
        "contact_id": contact_id,
        "contact_type": contact_type,
        "phone": phone,
        "email": email,
        "sequence_name": sequence_name,
        "current_step": 0,
        "status": "active",
        "context": context or {},
        "enrolled_at": datetime.now(timezone.utc).isoformat(),
    }).execute().data
    enrollment_id = enrollment[0]["id"] if enrollment else None

    # Schedule step 0 immediately
    await _schedule_step(business_id, enrollment_id, sequence_name, 0, phone, email, context or {})

    return {"enrolled": True, "enrollment_id": enrollment_id, "sequence": sequence_name}


async def advance_sequence(enrollment_id: str) -> dict:
    """
    Move an enrollment to the next step.
    Called by the sequence worker after a step completes.
    """
    sb = get_supabase()
    enrollment = sb.table("sequence_enrollments").select("*")\
        .eq("id", enrollment_id).limit(1).execute().data
    if not enrollment:
        return {"error": "Enrollment not found"}
    e = enrollment[0]

    if e["status"] != "active":
        return {"skipped": True, "reason": f"status={e['status']}"}

    next_step = e["current_step"] + 1
    sequence = SEQUENCES.get(e["sequence_name"], [])

    if next_step >= len(sequence):
        # Sequence complete
        sb.table("sequence_enrollments").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", enrollment_id).execute()
        return {"completed": True, "sequence": e["sequence_name"]}

    # Schedule next step
    step_config = sequence[next_step]
    send_at = datetime.now(timezone.utc) + timedelta(hours=step_config["delay_hours"])

    sb.table("sequence_enrollments").update({
        "current_step": next_step,
        "next_step_at": send_at.isoformat(),
    }).eq("id", enrollment_id).execute()

    # Schedule via task dispatcher
    await _schedule_step(
        e["business_id"], enrollment_id, e["sequence_name"],
        next_step, e["phone"], e["email"], e.get("context", {})
    )

    return {"advanced": True, "next_step": next_step, "send_at": send_at.isoformat()}


async def pause_sequence(enrollment_id: str, reason: str = "responded") -> None:
    """Pause a sequence (lead responded / booked / opted out)."""
    sb = get_supabase()
    sb.table("sequence_enrollments").update({
        "status": "paused",
        "pause_reason": reason,
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


async def check_and_pause_on_reply(business_id: str, phone: str) -> None:
    """
    When a lead/customer replies to ANY message, pause all their active sequences.
    Called by conversation_manager when inbound SMS received.
    """
    sb = get_supabase()
    active = sb.table("sequence_enrollments").select("id")\
        .eq("business_id", business_id).eq("phone", phone).eq("status", "active").execute().data or []
    for enrollment in active:
        await pause_sequence(enrollment["id"], reason="contact_replied")


async def get_due_steps(business_id: str) -> list[dict]:
    """Return all sequence steps that are due to send right now."""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    due = sb.table("sequence_enrollments").select("*")\
        .eq("business_id", business_id).eq("status", "active")\
        .lte("next_step_at", now).execute().data or []
    return due


async def run_due_sequences(business_id: str) -> dict:
    """
    Process all due sequence steps for a business.
    Called by the hourly heartbeat + 5-min urgent scanner.
    """
    due = await get_due_steps(business_id)
    sent = 0
    for enrollment in due:
        try:
            await _send_sequence_step(enrollment)
            sent += 1
        except Exception:
            pass
    return {"processed": len(due), "sent": sent}


async def _schedule_step(business_id: str, enrollment_id: str, sequence_name: str,
                          step_index: int, phone: str, email: str, context: dict) -> None:
    """Schedule a sequence step via task dispatcher."""
    sequence = SEQUENCES[sequence_name]
    step = sequence[step_index]
    send_at = datetime.now(timezone.utc) + timedelta(hours=step["delay_hours"])

    sb = get_supabase()
    sb.table("sequence_enrollments").update({
        "next_step_at": send_at.isoformat(),
    }).eq("id", enrollment_id).execute()


async def _send_sequence_step(enrollment: dict) -> None:
    """Actually send a sequence step message."""
    seq_name = enrollment["sequence_name"]
    step_idx = enrollment["current_step"]
    sequence = SEQUENCES.get(seq_name, [])
    if step_idx >= len(sequence):
        return

    step = sequence[step_idx]
    ctx = enrollment.get("context") or {}
    template_key = step["template"]
    channel = step["channel"]

    # Build message
    template = MESSAGE_TEMPLATES.get(template_key, "Hi {name}!")
    message = template.format(
        name=ctx.get("name", "there"),
        company=ctx.get("company", "your business"),
        industry=ctx.get("industry", "service"),
        booking_url=ctx.get("booking_url", os.getenv("CAL_COM_BASE_URL", "https://cal.com")),
        service=ctx.get("service", ""),
    )

    bid = enrollment["business_id"]
    phone = enrollment["phone"]
    email_addr = enrollment["email"]

    if channel == "sms" and phone:
        await dispatch(TaskRequest(
            business_id=UUID(bid),
            created_by="nurture_sequence",
            workflow="send_sms_campaign",
            priority=TaskPriority.NORMAL,
            parameters={"message": message, "phone": phone, "limit": 1},
        ))
    elif channel == "email" and email_addr:
        await dispatch(TaskRequest(
            business_id=UUID(bid),
            created_by="nurture_sequence",
            workflow="send_email_campaign",
            priority=TaskPriority.NORMAL,
            parameters={"subject": "Following up from your team", "body": message,
                        "recipient_email": email_addr, "limit": 1},
        ))

    # Mark step sent + advance
    sb = get_supabase()
    sb.table("sequence_enrollments").update({
        "last_step_sent_at": datetime.now(timezone.utc).isoformat(),
        "next_step_at": None,
    }).eq("id", enrollment["id"]).execute()

    await advance_sequence(enrollment["id"])


import os
