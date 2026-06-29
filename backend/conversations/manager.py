"""
Conversation Manager — full AI SDR flow.
Handles inbound SMS → qualifies → books Cal.com appointment directly in the conversation.
State: new → contacted → replied → qualifying → interested → booked | not_now | dead
"""
import os
import json
import httpx
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


class ConvState:
    NEW        = "new"
    CONTACTED  = "contacted"
    REPLIED    = "replied"
    QUALIFYING = "qualifying"
    INTERESTED = "interested"
    BOOKED     = "booked"
    NOT_NOW    = "not_now"
    DEAD       = "dead"


STOP_WORDS    = ["stop", "unsubscribe", "opt out", "remove me", "no thanks", "not interested"]
BOOK_WORDS    = ["yes", "book", "schedule", "appointment", "interested", "sign me up", "let's do it", "demo", "sure"]
NOT_NOW_WORDS = ["not now", "maybe later", "busy", "call me", "next month", "not ready"]


async def get_or_create_conversation(business_id: str, phone: str, lead_id: str = None,
                                      customer_id: str = None) -> dict:
    sb = get_supabase()
    r = sb.table("conversations").select("*").eq("business_id", business_id)\
        .eq("contact_phone", phone).limit(1).execute()
    if r.data:
        return r.data[0]
    result = sb.table("conversations").insert({
        "business_id": business_id,
        "contact_phone": phone,
        "lead_id": lead_id,
        "customer_id": customer_id,
        "state": ConvState.NEW,
        "message_count": 0,
        "messages": [],
    }).execute()
    return result.data[0] if result.data else {}


async def handle_inbound_sms(business_id: str, payload: dict) -> None:
    """Route inbound SMS through AI SDR → qualify → book."""
    from_phone = payload.get("from", payload.get("from_number", ""))
    message_body = payload.get("body", payload.get("text", ""))
    if not from_phone or not message_body:
        return

    # Pause any active nurture sequences
    from backend.integrations.nurture_sequences import check_and_pause_on_reply
    await check_and_pause_on_reply(business_id, from_phone)

    sb = get_supabase()
    customer = sb.table("customers").select("id,name,tags,lifetime_value")\
        .eq("business_id", business_id).eq("phone", from_phone).limit(1).execute()
    customer = customer.data[0] if customer.data else None
    lead = sb.table("leads").select("id,company_name,score,status,email")\
        .eq("business_id", business_id).eq("phone", from_phone).limit(1).execute()
    lead = lead.data[0] if lead.data else None

    conv = await get_or_create_conversation(
        business_id, from_phone,
        lead_id=lead["id"] if lead else None,
        customer_id=customer["id"] if customer else None,
    )

    messages = conv.get("messages") or []
    messages.append({"role": "customer", "text": message_body,
                     "timestamp": datetime.now(timezone.utc).isoformat()})

    msg_lower = message_body.lower()
    current_state = conv.get("state", ConvState.NEW)

    # Hard stop
    if any(w in msg_lower for w in STOP_WORDS):
        await _send_sms(from_phone, "Got it — we'll stop messaging you. Take care! 😊")
        _update_conv(sb, conv["id"], ConvState.DEAD, messages, message_body)
        if lead:
            sb.table("leads").update({"status": "dead"}).eq("id", lead["id"]).execute()
        return

    # Detect booking intent → offer booking link or check availability
    if any(w in msg_lower for w in BOOK_WORDS) or current_state == ConvState.INTERESTED:
        booking_url = await _get_booking_url(business_id)
        biz = sb.table("businesses").select("name").eq("id", business_id).limit(1).execute()
        biz_name = biz.data[0]["name"] if biz.data else "us"
        name = (customer or lead or {}).get("name") or (lead or {}).get("company_name") or "there"
        reply = (f"Amazing, {name}! 🎉 Here's your booking link: {booking_url} — "
                 f"pick any time that works and we'll confirm right away. See you soon!")
        await _send_sms(from_phone, reply)
        messages.append({"role": "ai", "text": reply, "timestamp": datetime.now(timezone.utc).isoformat()})
        _update_conv(sb, conv["id"], ConvState.INTERESTED, messages, message_body)
        if lead:
            sb.table("leads").update({"status": "interested"}).eq("id", lead["id"]).execute()
        return

    # AI SDR generates a contextual reply
    reply = await _generate_sdr_reply(business_id, conv, message_body, customer, lead, messages)
    if reply:
        await _send_sms(from_phone, reply)
        messages.append({"role": "ai", "text": reply, "timestamp": datetime.now(timezone.utc).isoformat()})

    new_state = _next_state(current_state, msg_lower)
    _update_conv(sb, conv["id"], new_state, messages, message_body)

    if lead:
        sb.table("leads").update({"status": "contacted"}).eq("id", lead["id"]).execute()

    # Publish event
    from backend.events.bus import publish, E
    await publish(business_id, E.LEAD_REPLIED, {
        "lead_id": lead["id"] if lead else None,
        "phone": from_phone,
        "message": message_body,
        "conversation_id": conv["id"],
        "state": new_state,
    })


async def _generate_sdr_reply(business_id: str, conv: dict, inbound: str,
                                customer: dict, lead: dict, messages: list) -> str:
    """GPT-4o-mini AI SDR — qualifies leads and moves them toward booking."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    sb = get_supabase()
    biz = sb.table("businesses").select("name,industry").eq("id", business_id).limit(1).execute()
    biz = biz.data[0] if biz.data else {}
    booking_url = await _get_booking_url(business_id)

    contact_name = ""
    if customer:
        contact_name = customer.get("name", "")
    elif lead:
        contact_name = lead.get("company_name", "")

    history = "\n".join([f"{m['role'].upper()}: {m['text']}" for m in messages[-6:]])
    state = conv.get("state", ConvState.NEW)

    system = f"""You are the AI sales rep for {biz.get('name','this business')}, a {biz.get('industry','service')} business in New Jersey.

Your goal: qualify this person's interest and get them to book an appointment.

Rules:
- Keep messages SHORT — 1-3 sentences max (SMS)
- Be warm, human, conversational — not salesy
- Ask ONE question at a time
- When they show interest: give booking link {booking_url}
- Never be pushy. If they're not ready, acknowledge and offer to follow up later

Contact name: {contact_name or 'unknown'}
Current stage: {state}
Conversation:
{history}

Next reply (SMS only, very short):"""

    llm = ChatOpenAI(
        model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
        api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"They said: {inbound}"),
        ])
        return resp.content.strip()
    except Exception:
        return ""


async def _get_booking_url(business_id: str) -> str:
    """Get the Cal.com booking URL for this business."""
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        biz = sb.table("businesses").select("config").eq("id", business_id).limit(1).execute()
        if biz.data:
            config = biz.data[0].get("config") or {}
            if config.get("booking_url"):
                return config["booking_url"]
    except Exception:
        pass
    base = os.getenv("CAL_COM_BASE_URL", "https://cal.com")
    return base


async def check_availability_calcom(date: str = None, service: str = None) -> dict:
    """Check Cal.com availability and return available slots."""
    api_key = os.getenv("CAL_COM_API_KEY", "")
    base = os.getenv("CAL_COM_BASE_URL", "https://api.cal.com/v2")
    event_type_id = os.getenv("CAL_COM_EVENT_TYPE_30MIN", "")
    if not api_key or not event_type_id:
        return {"available_slots": [], "error": "Cal.com not configured"}
    try:
        from datetime import timedelta
        start = date or datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/slots/available",
                headers={"Authorization": f"Bearer {api_key}",
                         "cal-api-version": os.getenv("CAL_COM_API_VERSION", "2024-08-13")},
                params={"eventTypeId": event_type_id, "startTime": start, "endTime": end},
            )
            resp.raise_for_status()
            data = resp.json()
        slots = data.get("data", {}).get("slots", {})
        available = []
        for day, day_slots in list(slots.items())[:3]:
            for slot in day_slots[:2]:
                available.append({"date": day, "time": slot.get("time", "")})
        return {"available_slots": available, "booking_url": await _get_booking_url("")}
    except Exception as e:
        return {"available_slots": [], "error": str(e)}


async def _send_sms(to_phone: str, message: str) -> None:
    """Send SMS via Telnyx."""
    telnyx_key = os.getenv("TELNYX_API_KEY", "")
    from_number = os.getenv("TELNYX_PHONE_NUMBER", "")
    if not telnyx_key or not from_number:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "https://api.telnyx.com/v2/messages",
                headers={"Authorization": f"Bearer {telnyx_key}"},
                json={"from": from_number, "to": to_phone, "text": message},
            )
    except Exception:
        pass


def _next_state(current: str, msg_lower: str) -> str:
    if any(w in msg_lower for w in NOT_NOW_WORDS):
        return ConvState.NOT_NOW
    if any(w in msg_lower for w in BOOK_WORDS):
        return ConvState.INTERESTED
    if current in (ConvState.NEW, ConvState.CONTACTED):
        return ConvState.REPLIED
    if current == ConvState.REPLIED:
        return ConvState.QUALIFYING
    return current


def _update_conv(sb, conv_id: str, state: str, messages: list, last_inbound: str) -> None:
    sb.table("conversations").update({
        "state": state,
        "messages": messages,
        "message_count": len(messages),
        "last_message_at": datetime.now(timezone.utc).isoformat(),
        "last_inbound": last_inbound,
    }).eq("id", conv_id).execute()


async def continue_lead_conversation(business_id: str, payload: dict) -> None:
    """CMO handler: lead replied to outreach."""
    phone = payload.get("phone", "")
    if phone:
        await handle_inbound_sms(business_id, {"from": phone, "body": payload.get("message", "")})
