"""
Webhooks — inbound events from Telnyx (SMS) and VAPI (calls).
Each webhook publishes to the event bus for autonomous agent handling.

Signature verification is applied per-provider and is graceful: if the relevant
secret env var is unset we skip verification (with a printed warning) so local
dev keeps working; if the secret IS set and verification fails we return 401.
"""
import os
import hmac
import hashlib
import base64

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()


# ── Signature verification helpers ────────────────────────────

def _verify_telnyx(request: Request, raw_body: bytes) -> None:
    """Verify Telnyx Ed25519 signature over f"{timestamp}|{raw_body}".

    Skips (with warning) if TELNYX_PUBLIC_KEY is unset or the cryptography lib
    isn't importable. Raises HTTPException(401) on a real verification failure.
    """
    public_key_b64 = os.getenv("TELNYX_PUBLIC_KEY")
    if not public_key_b64:
        print("[webhooks] TELNYX_PUBLIC_KEY unset — skipping Telnyx signature verification")
        return
    try:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature
        except Exception:
            print("[webhooks] cryptography lib unavailable — skipping Telnyx signature verification")
            return

        signature_b64 = request.headers.get("telnyx-signature-ed25519", "")
        timestamp = request.headers.get("telnyx-timestamp", "")
        if not signature_b64 or not timestamp:
            raise HTTPException(status_code=401, detail="missing Telnyx signature headers")

        signed_payload = f"{timestamp}|".encode() + raw_body
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        try:
            public_key.verify(base64.b64decode(signature_b64), signed_payload)
        except InvalidSignature:
            raise HTTPException(status_code=401, detail="invalid Telnyx signature")
    except HTTPException:
        raise
    except Exception as e:
        # Never crash the request on an unexpected verification-path error.
        print(f"[webhooks] Telnyx signature verification error (skipping): {e}")


def _verify_vapi(request: Request) -> None:
    """Verify VAPI shared secret via constant-time compare of x-vapi-secret."""
    secret = os.getenv("VAPI_WEBHOOK_SECRET")
    if not secret:
        print("[webhooks] VAPI_WEBHOOK_SECRET unset — skipping VAPI signature verification")
        return
    try:
        provided = request.headers.get("x-vapi-secret", "")
        if not hmac.compare_digest(provided, secret):
            raise HTTPException(status_code=401, detail="invalid VAPI secret")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[webhooks] VAPI signature verification error (skipping): {e}")


def _verify_calcom(request: Request, raw_body: bytes) -> None:
    """Verify Cal.com HMAC-SHA256 signature over the raw body."""
    secret = os.getenv("CAL_WEBHOOK_SECRET")
    if not secret:
        print("[webhooks] CAL_WEBHOOK_SECRET unset — skipping Cal.com signature verification")
        return
    try:
        provided = request.headers.get("x-cal-signature-256", "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid Cal.com signature")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[webhooks] Cal.com signature verification error (skipping): {e}")


# ── Multi-tenant routing helper ───────────────────────────────

def _business_for_phone(sb, to_number: str):
    """Resolve which business owns an inbound destination phone number.

    Matches against businesses.phone, businesses.config->>phone, and the
    config.telnyx_number / config.vapi_number values. Falls back to the first
    business only if nothing matches.
    """
    if to_number:
        try:
            # Direct column match
            r = sb.table("businesses").select("id").eq("phone", to_number).limit(1).execute()
            if r.data:
                return r.data[0]["id"]
        except Exception:
            pass
        try:
            # JSON config match (config->>phone)
            r = sb.table("businesses").select("id").eq("config->>phone", to_number).limit(1).execute()
            if r.data:
                return r.data[0]["id"]
        except Exception:
            pass
        try:
            # Scan configs for telnyx_number / vapi_number matches
            rows = sb.table("businesses").select("id,config").execute().data or []
            for row in rows:
                cfg = row.get("config") or {}
                if not isinstance(cfg, dict):
                    continue
                if to_number in (cfg.get("phone"), cfg.get("telnyx_number"), cfg.get("vapi_number")):
                    return row["id"]
        except Exception:
            pass

    # TODO multi-tenant: no phone match — fall back to first business.
    try:
        biz = sb.table("businesses").select("id").limit(1).execute()
        return biz.data[0]["id"] if biz.data else None
    except Exception:
        return None


@router.post("/webhooks/sms/inbound")
async def telnyx_sms_inbound(request: Request):
    """Telnyx inbound SMS webhook — fires sms.received event."""
    try:
        raw_body = await request.body()
        _verify_telnyx(request, raw_body)

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
        business_id = _business_for_phone(sb, to_number)
        if not business_id:
            return JSONResponse({"status": "no_business"})

        # Publish event — autonomous agents handle the rest
        from backend.events.bus import publish, E
        await publish(business_id, E.SMS_RECEIVED, {
            "from": from_number,
            "to": to_number,
            "body": message_body,
            "direction": "inbound",
        }, source="telnyx_webhook")

        return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})


@router.post("/webhooks/vapi/call")
async def vapi_call_webhook(request: Request):
    """VAPI call webhook — handles call events."""
    try:
        _verify_vapi(request)

        body = await request.json()
        msg_type = body.get("message", {}).get("type", "")
        call = body.get("message", {}).get("call", body.get("call", {}))

        customer_number = call.get("customer", {}).get("number", "")
        call_id = call.get("id", "")
        # Destination number the customer dialed (used for tenant routing).
        to_number = (
            call.get("phoneNumber", {}).get("number", "")
            if isinstance(call.get("phoneNumber"), dict)
            else call.get("phoneNumber", "")
        )

        from backend.memory.supabase_client import get_supabase
        from backend.events.bus import publish, E
        sb = get_supabase()
        business_id = _business_for_phone(sb, to_number)
        if not business_id:
            return JSONResponse({"status": "no_business"})

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
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})


@router.post("/webhooks/appointment")
async def appointment_event(request: Request):
    """Generic appointment webhook — called by Cal.com or booking system."""
    try:
        raw_body = await request.body()
        _verify_calcom(request, raw_body)

        body = await request.json()
        event_type = body.get("triggerEvent", body.get("type", ""))
        payload = body.get("payload", body)

        from backend.memory.supabase_client import get_supabase
        from backend.events.bus import publish, E
        sb = get_supabase()
        biz = sb.table("businesses").select("id").limit(1).execute()
        business_id = biz.data[0]["id"] if biz.data else None  # TODO multi-tenant: Cal.com payload has no destination phone
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
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})
