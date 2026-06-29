"""
Webhooks — inbound events from Telnyx (SMS) and VAPI (calls).
Each webhook publishes to the event bus for autonomous agent handling.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/webhooks/sms/inbound")
async def telnyx_sms_inbound(request: Request):
    """Telnyx inbound SMS webhook — fires sms.received event."""
    try:
        body = await request.json()
        data = body.get("data", {}).get("payload", body.get("payload", body))

        from_number = data.get("from", {}).get("phone_number", "") if isinstance(data.get("from"), dict) else data.get("from", "")
        to_number = data.get("to", [{}])[0].get("phone_number", "") if isinstance(data.get("to"), list) else data.get("to", "")
        message_body = data.get("text", data.get("body", ""))

        if not from_number or not message_body:
            return JSONResponse({"status": "ignored"})

        # Find which business owns this phone number
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        biz = sb.table("businesses").select("id").limit(1).execute()
        if not biz.data:
            return JSONResponse({"status": "no_business"})

        business_id = biz.data[0]["id"]  # TODO: match by phone number when multi-tenant

        # Publish event — autonomous agents handle the rest
        from backend.events.bus import publish, E
        await publish(business_id, E.SMS_RECEIVED, {
            "from": from_number,
            "to": to_number,
            "body": message_body,
            "direction": "inbound",
        }, source="telnyx_webhook")

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})


@router.post("/webhooks/vapi/call")
async def vapi_call_webhook(request: Request):
    """VAPI call webhook — handles call events."""
    try:
        body = await request.json()
        msg_type = body.get("message", {}).get("type", "")
        call = body.get("message", {}).get("call", body.get("call", {}))

        customer_number = call.get("customer", {}).get("number", "")
        call_id = call.get("id", "")

        from backend.memory.supabase_client import get_supabase
        from backend.events.bus import publish, E
        sb = get_supabase()
        biz = sb.table("businesses").select("id").limit(1).execute()
        if not biz.data:
            return JSONResponse({"status": "no_business"})
        business_id = biz.data[0]["id"]

        if msg_type == "end-of-call-report":
            transcript = body.get("message", {}).get("transcript", "")
            summary = body.get("message", {}).get("summary", "")
            ended_reason = body.get("message", {}).get("endedReason", "")

            if ended_reason == "customer-did-not-answer":
                await publish(business_id, E.CALL_MISSED, {
                    "customer_phone": customer_number,
                    "call_id": call_id,
                }, source="vapi_webhook")
            else:
                await publish(business_id, E.CALL_COMPLETED, {
                    "customer_phone": customer_number,
                    "call_id": call_id,
                    "transcript": transcript,
                    "summary": summary,
                    "outcome": ended_reason,
                }, source="vapi_webhook")

                # Log call to Supabase
                sb.table("calls").insert({
                    "business_id": business_id,
                    "direction": "inbound",
                    "caller_phone": customer_number,
                    "transcript": transcript[:2000],
                    "summary": summary,
                    "status": "completed",
                }).execute()

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})


@router.post("/webhooks/appointment")
async def appointment_event(request: Request):
    """Generic appointment webhook — called by Cal.com or booking system."""
    try:
        body = await request.json()
        event_type = body.get("triggerEvent", body.get("type", ""))
        payload = body.get("payload", body)

        from backend.memory.supabase_client import get_supabase
        from backend.events.bus import publish, E
        sb = get_supabase()
        biz = sb.table("businesses").select("id").limit(1).execute()
        business_id = biz.data[0]["id"] if biz.data else None
        if not business_id:
            return JSONResponse({"status": "no_business"})

        event_map = {
            "BOOKING_CREATED": E.APPT_BOOKED,
            "BOOKING_CANCELLED": E.APPT_CANCELLED,
            "BOOKING_RESCHEDULED": E.APPT_BOOKED,
        }
        mapped = event_map.get(event_type, "")
        if mapped:
            await publish(business_id, mapped, {
                "appointment_id": payload.get("uid", payload.get("bookingId", "")),
                "customer_name": payload.get("attendees", [{}])[0].get("name", "") if payload.get("attendees") else "",
                "customer_email": payload.get("attendees", [{}])[0].get("email", "") if payload.get("attendees") else "",
                "scheduled_at": payload.get("startTime", ""),
                "service": payload.get("eventType", {}).get("title", "") if isinstance(payload.get("eventType"), dict) else "",
            }, source="calcom_webhook")

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})
