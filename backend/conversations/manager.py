"""
Conversation Manager — tracks SMS/lead conversation state.
When a lead or customer replies, we know where they are in the flow
and respond intelligently using the right agent.
"""
import json
import os
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


# Conversation states
class ConvState:
    NEW          = "new"           # Just discovered
    CONTACTED    = "contacted"     # We sent first message
    REPLIED      = "replied"       # They replied
    QUALIFYING   = "qualifying"    # Ongoing qualification conversation
    INTERESTED   = "interested"    # Expressed interest
    BOOKED       = "booked"        # Booked appointment
    NOT_NOW      = "not_now"       # Not interested right now
    DEAD         = "dead"          # Explicitly declined


async def get_or_create_conversation(business_id: str, phone: str, lead_id: str = None) -> dict:
    """Get existing conversation or create new one."""
    sb = get_supabase()
    r = sb.table("conversations").select("*").eq("business_id", business_id) \
        .eq("contact_phone", phone).limit(1).execute()
    if r.data:
        return r.data[0]
    # Create new
    result = sb.table("conversations").insert({
        "business_id": business_id,
        "contact_phone": phone,
        "lead_id": lead_id,
        "state": ConvState.NEW,
        "message_count": 0,
        "messages": [],
    }).execute()
    return result.data[0] if result.data else {}


async def handle_inbound_sms(business_id: str, payload: dict) -> None:
    """
    Handle an inbound SMS from a customer or lead.
    Routes to the right agent based on conversation state and context.
    """
    from_phone = payload.get("from", payload.get("from_number", ""))
    message_body = payload.get("body", payload.get("text", ""))

    if not from_phone or not message_body:
        return

    sb = get_supabase()

    # Find if this is a known customer
    customer = sb.table("customers").select("id,name,tags").eq("business_id", business_id) \
        .eq("phone", from_phone).limit(1).execute()
    customer = customer.data[0] if customer.data else None

    # Find if this is a known lead
    lead = sb.table("leads").select("id,company_name,score,status").eq("business_id", business_id) \
        .eq("phone", from_phone).limit(1).execute()
    lead = lead.data[0] if lead.data else None

    # Get/create conversation
    conv = await get_or_create_conversation(
        business_id, from_phone,
        lead_id=lead["id"] if lead else None
    )

    # Store the inbound message
    messages = conv.get("messages", []) or []
    messages.append({
        "role": "customer",
        "text": message_body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Decide reply using the right agent
    reply_text = await _generate_reply(
        business_id=business_id,
        conversation=conv,
        inbound_message=message_body,
        customer=customer,
        lead=lead,
        messages=messages,
    )

    # Send reply via Telnyx
    if reply_text:
        await _send_sms_reply(business_id, from_phone, reply_text)
        messages.append({
            "role": "ai",
            "text": reply_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Update conversation state
    new_state = _determine_state(conv.get("state", ConvState.NEW), message_body, reply_text)
    sb.table("conversations").update({
        "state": new_state,
        "messages": messages,
        "message_count": len(messages),
        "last_message_at": datetime.now(timezone.utc).isoformat(),
        "last_inbound": message_body,
    }).eq("id", conv["id"]).execute()

    # Update lead status if applicable
    if lead:
        sb.table("leads").update({"status": "contacted"}).eq("id", lead["id"]).execute()
        # Publish event so CMO knows they replied
        from backend.events.bus import publish, E
        await publish(business_id, E.LEAD_REPLIED, {
            "lead_id": lead["id"],
            "phone": from_phone,
            "message": message_body,
            "conversation_id": conv["id"],
        })


async def _generate_reply(
    business_id: str,
    conversation: dict,
    inbound_message: str,
    customer: dict,
    lead: dict,
    messages: list,
) -> str:
    """Use the right agent to generate a smart reply."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    sb = get_supabase()
    biz = sb.table("businesses").select("name,industry,timezone").eq("id", business_id).limit(1).execute()
    biz = biz.data[0] if biz.data else {}

    # Build conversation history
    history = "\n".join([
        f"{m['role'].upper()}: {m['text']}"
        for m in messages[-6:]  # last 6 messages for context
    ])

    contact_name = (customer or lead or {}).get("name") or (lead or {}).get("company_name") or "there"

    system = f"""You are the AI receptionist for {biz.get('name', 'this business')}, a {biz.get('industry', 'service')} business.

Your job: reply to this SMS conversation naturally and helpfully.
- Be warm, professional, conversational
- Keep replies SHORT (1-3 sentences max for SMS)
- Goal: qualify interest → book appointment or get contact info
- If they want to book → give them a booking link or ask for preferred time
- If they say STOP → acknowledge and stop
- Never be pushy

Contact: {contact_name}
Conversation so far:
{history}"""

    llm = ChatOpenAI(model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                     api_key=os.getenv("OPENAI_API_KEY", ""))
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"They just said: {inbound_message}\n\nReply (SMS, keep short):"),
        ])
        return resp.content.strip()
    except Exception:
        return ""


def _determine_state(current_state: str, inbound: str, reply: str) -> str:
    """Simple state machine based on message content."""
    inbound_lower = inbound.lower()
    if any(w in inbound_lower for w in ["stop", "unsubscribe", "opt out", "remove me"]):
        return ConvState.DEAD
    if any(w in inbound_lower for w in ["book", "yes", "interested", "schedule", "appointment"]):
        return ConvState.INTERESTED
    if any(w in inbound_lower for w in ["not now", "maybe later", "no thanks", "not interested"]):
        return ConvState.NOT_NOW
    if current_state in (ConvState.NEW, ConvState.CONTACTED):
        return ConvState.REPLIED
    if current_state == ConvState.REPLIED:
        return ConvState.QUALIFYING
    return current_state


async def _send_sms_reply(business_id: str, to_phone: str, message: str) -> None:
    """Send SMS reply via Telnyx."""
    import httpx
    telnyx_key = os.getenv("TELNYX_API_KEY", "")
    from_number = os.getenv("TELNYX_PHONE_NUMBER", "")
    if not telnyx_key or not from_number:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.telnyx.com/v2/messages",
            headers={"Authorization": f"Bearer {telnyx_key}"},
            json={"from": from_number, "to": to_phone, "text": message},
            timeout=10,
        )


async def continue_lead_conversation(business_id: str, payload: dict) -> None:
    """CMO handler: lead replied to outreach, continue the conversation."""
    phone = payload.get("phone", "")
    if phone:
        await handle_inbound_sms(business_id, {
            "from": phone,
            "body": payload.get("message", ""),
        })
