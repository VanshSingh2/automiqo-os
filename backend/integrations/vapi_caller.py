"""
VAPI Outbound Caller — initiates AI phone calls to customers and leads.
Used by CRO, CSD, and COO for:
  - Missed call recovery (call back within 5 min)
  - Dormant customer reactivation
  - Appointment reminders (voice)
  - Post-visit follow-up
  - Lead qualification calls

VAPI API: https://api.vapi.ai
Each call uses a pre-configured VAPI assistant with the business persona.
"""
import os
import httpx
import json
from typing import Optional
from datetime import datetime, timezone

VAPI_BASE = "https://api.vapi.ai"


async def make_outbound_call(
    customer_phone: str,
    business_id: str,
    purpose: str,
    context: dict = None,
    assistant_id: str = None,
) -> dict:
    """
    Initiate an outbound AI call via VAPI.

    Args:
        customer_phone:  E.164 format e.g. +12015550123
        business_id:     For logging to Supabase
        purpose:         'missed_call_recovery' | 'reactivation' | 'reminder' | 'follow_up' | 'lead_qualification'
        context:         Dict passed to VAPI assistant as metadata (customer name, reason, etc.)
        assistant_id:    VAPI assistant ID (defaults to VAPI_ASSISTANT_ID env var)

    Returns:
        {"call_id": "...", "status": "queued", ...}
    """
    vapi_key = os.getenv("VAPI_API_KEY", "")
    if not vapi_key:
        return {"error": "VAPI_API_KEY not configured"}

    phone_number_id = os.getenv("VAPI_PHONE_NUMBER_ID", "")
    asst_id = assistant_id or os.getenv("VAPI_ASSISTANT_ID", "")

    # Build dynamic first message based on purpose
    first_message = _build_first_message(purpose, context or {})

    payload = {
        "phoneNumberId": phone_number_id,
        "customer": {"number": customer_phone},
        "assistantId": asst_id,
        "assistantOverrides": {
            "firstMessage": first_message,
            "metadata": {
                "business_id": business_id,
                "purpose": purpose,
                **(context or {}),
            },
        },
    }

    # Remove empty fields
    if not phone_number_id:
        del payload["phoneNumberId"]
        payload["assistant"] = {
            "model": {"provider": "openai", "model": "gpt-4o-mini"},
            "firstMessage": first_message,
            "voice": {"provider": "11labs", "voiceId": os.getenv("VAPI_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")},
        }
        del payload["assistantId"]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{VAPI_BASE}/call",
                headers={
                    "Authorization": f"Bearer {vapi_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()

        # Log call to Supabase
        await _log_outbound_call(business_id, customer_phone, purpose, result.get("id"), context)

        return {
            "call_id": result.get("id"),
            "status": result.get("status", "queued"),
            "purpose": purpose,
            "customer_phone": customer_phone,
        }

    except httpx.HTTPStatusError as e:
        return {"error": f"VAPI API error {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


async def make_missed_call_recovery(customer_phone: str, business_id: str,
                                     customer_name: str = "", business_name: str = "") -> dict:
    """Call back a customer who missed their call within 5 minutes."""
    return await make_outbound_call(
        customer_phone=customer_phone,
        business_id=business_id,
        purpose="missed_call_recovery",
        context={"customer_name": customer_name, "business_name": business_name},
    )


async def make_reactivation_call(customer_phone: str, business_id: str,
                                  customer_name: str = "", days_inactive: int = 30,
                                  last_service: str = "") -> dict:
    """Call a dormant customer to reactivate them."""
    return await make_outbound_call(
        customer_phone=customer_phone,
        business_id=business_id,
        purpose="reactivation",
        context={
            "customer_name": customer_name,
            "days_inactive": days_inactive,
            "last_service": last_service,
        },
    )


async def make_appointment_reminder_call(customer_phone: str, business_id: str,
                                          customer_name: str = "", appointment_time: str = "",
                                          service: str = "") -> dict:
    """Voice reminder for upcoming appointment."""
    return await make_outbound_call(
        customer_phone=customer_phone,
        business_id=business_id,
        purpose="reminder",
        context={
            "customer_name": customer_name,
            "appointment_time": appointment_time,
            "service": service,
        },
    )


async def make_lead_qualification_call(lead_phone: str, business_id: str,
                                        lead_name: str = "", industry: str = "") -> dict:
    """AI SDR call to qualify a warm lead."""
    return await make_outbound_call(
        customer_phone=lead_phone,
        business_id=business_id,
        purpose="lead_qualification",
        context={"lead_name": lead_name, "industry": industry},
    )


async def make_follow_up_call(customer_phone: str, business_id: str,
                               customer_name: str = "", service: str = "") -> dict:
    """Post-visit follow-up call."""
    return await make_outbound_call(
        customer_phone=customer_phone,
        business_id=business_id,
        purpose="follow_up",
        context={"customer_name": customer_name, "service": service},
    )


async def get_call_status(call_id: str) -> dict:
    """Get the status and transcript of a VAPI call."""
    vapi_key = os.getenv("VAPI_API_KEY", "")
    if not vapi_key:
        return {"error": "VAPI_API_KEY not configured"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{VAPI_BASE}/call/{call_id}",
                headers={"Authorization": f"Bearer {vapi_key}"},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


def _build_first_message(purpose: str, ctx: dict) -> str:
    """Build a natural first message for each call purpose."""
    name = ctx.get("customer_name") or ctx.get("lead_name") or ""
    greeting = f"Hi{', ' + name if name else ''}!"

    messages = {
        "missed_call_recovery": (
            f"{greeting} This is {ctx.get('business_name', 'our team')} calling back — "
            "we saw you tried to reach us just now. How can I help you today?"
        ),
        "reactivation": (
            f"{greeting} This is your team at {ctx.get('business_name', 'the studio')}. "
            f"We haven't seen you in a little while and wanted to check in. "
            "Would you like to schedule a visit soon?"
        ),
        "reminder": (
            f"{greeting} Quick reminder about your upcoming appointment "
            f"{('for ' + ctx['service']) if ctx.get('service') else ''} "
            f"{('at ' + ctx['appointment_time']) if ctx.get('appointment_time') else 'coming up'}. "
            "Just confirming you're all set — are you still good to go?"
        ),
        "lead_qualification": (
            f"{greeting} I'm reaching out because you showed interest in our services. "
            "I'd love to learn a bit about your business and see if we can help. "
            "Do you have 2 minutes?"
        ),
        "follow_up": (
            f"{greeting} We just wanted to follow up after your recent visit "
            f"{('for ' + ctx['service']) if ctx.get('service') else ''}. "
            "How was your experience? Is there anything we can do better?"
        ),
    }
    return messages.get(purpose, f"{greeting} Calling from our team — how can I help?")


async def _log_outbound_call(business_id: str, phone: str, purpose: str,
                              call_id: str, context: dict) -> None:
    """Log the outbound call to Supabase calls table."""
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        sb.table("calls").insert({
            "business_id": business_id,
            "direction": "outbound",
            "caller_phone": phone,
            "status": "initiated",
            "outcome": purpose,
            "vapi_call_id": call_id,
            "summary": f"Outbound {purpose} call",
            "called_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass
