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


def _verify_email(request: Request, raw_body: bytes) -> None:
    """Verify a provider-agnostic inbound-email HMAC-SHA256 signature.

    The sender must sign the raw request body with the shared secret
    EMAIL_WEBHOOK_SECRET and send the lowercase hex digest in the
    'x-email-signature-256' header.

    Skips (with warning) if EMAIL_WEBHOOK_SECRET is unset so local dev keeps
    working. Raises HTTPException(401) on a real verification failure.
    """
    secret = os.getenv("EMAIL_WEBHOOK_SECRET")
    if not secret:
        print("[webhooks] EMAIL_WEBHOOK_SECRET unset — skipping email signature verification")
        return
    try:
        provided = request.headers.get("x-email-signature-256", "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid email signature")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[webhooks] email signature verification error (skipping): {e}")


def _verify_whatsapp(request: Request, raw_body: bytes) -> None:
    """Verify a provider-agnostic inbound-WhatsApp HMAC-SHA256 signature.

    The sender must sign the raw request body with the shared secret
    WHATSAPP_WEBHOOK_SECRET and send the lowercase hex digest in the
    'x-whatsapp-signature-256' header.

    Skips (with warning) if WHATSAPP_WEBHOOK_SECRET is unset so local dev keeps
    working. Raises HTTPException(401) on a real verification failure.
    Mirrors _verify_email.
    """
    secret = os.getenv("WHATSAPP_WEBHOOK_SECRET")
    if not secret:
        print("[webhooks] WHATSAPP_WEBHOOK_SECRET unset — skipping WhatsApp signature verification")
        return
    try:
        provided = request.headers.get("x-whatsapp-signature-256", "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid WhatsApp signature")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[webhooks] WhatsApp signature verification error (skipping): {e}")


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


def _business_for_email(sb, to_addr: str):
    """Resolve which business owns an inbound destination email address.

    Matches against businesses.config->>support_email and config->>email; if
    nothing matches (or the address is missing) falls back to the first
    business. Fully defensive — never raises.
    """
    if to_addr:
        try:
            rows = sb.table("businesses").select("id,config").execute().data or []
            for row in rows:
                cfg = row.get("config") or {}
                if not isinstance(cfg, dict):
                    continue
                if to_addr in (cfg.get("support_email"), cfg.get("email")):
                    return row["id"]
        except Exception:
            pass

    # TODO multi-tenant: no email match — fall back to first business
    # (mirrors the appointment webhook's single-tenant fallback).
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



@router.post("/webhooks/email/inbound")
async def email_inbound(request: Request):
    """Provider-agnostic inbound email webhook — fires email.received event.

    The autonomous org can now 'hear' inbound customer emails (previously only
    SMS/calls). Accepts a range of provider payload shapes with graceful
    fallbacks (Mailgun, SendGrid, Postmark, generic JSON).
    """
    try:
        raw_body = await request.body()
        _verify_email(request, raw_body)

        body = await request.json()

        # Provider-agnostic field extraction with graceful fallbacks.
        from_addr = (
            body.get("from")
            or body.get("sender")
            or (body.get("envelope", {}) or {}).get("from")
        )
        to_addr = body.get("to") or body.get("recipient")
        subject = body.get("subject", "")
        text = (
            body.get("text")
            or body.get("body-plain")
            or body.get("stripped-text")
            or body.get("body", "")
        )

        if not from_addr or not text:
            return JSONResponse({"status": "ignored"})

        # Resolve which business owns this destination address (best-effort).
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        business_id = _business_for_email(sb, to_addr)
        if not business_id:
            return JSONResponse({"status": "no_business"})

        # Publish event — autonomous agents handle the rest.
        from backend.events.bus import publish
        await publish(business_id, "email.received", {
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "body": text[:4000],
            "channel": "email",
            "direction": "inbound",
        }, source="email_webhook")

        # Best-effort: log the inbound message to Supabase.
        try:
            from datetime import datetime, timezone
            sb.table("messages").insert({
                "business_id": business_id,
                "direction": "inbound",
                "channel": "email",
                "body": text[:4000],
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

        return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})



@router.post("/webhooks/whatsapp/inbound")
async def whatsapp_inbound(request: Request):
    """Provider-agnostic inbound WhatsApp webhook — fires whatsapp.received event.

    The autonomous org can now 'hear' inbound customer WhatsApp messages (in
    addition to SMS/calls/email) and auto-handle them via the same conversational
    SDR flow used for SMS. Accepts a range of provider payload shapes with
    graceful fallbacks (Twilio WhatsApp, Meta Cloud API, generic JSON).
    """
    try:
        raw_body = await request.body()
        _verify_whatsapp(request, raw_body)

        body = await request.json()

        # Provider-agnostic field extraction with graceful fallbacks.
        from_number = (
            body.get("from")
            or body.get("From")
            or body.get("WaId")
            or (body.get("messages", [{}])[0].get("from") if body.get("messages") else "")
        )
        to_number = body.get("to") or body.get("To")
        text = (
            body.get("text")
            or body.get("Body")
            or (body.get("messages", [{}])[0].get("text", {}).get("body") if body.get("messages") else "")
            or ""
        )

        if not from_number or not text:
            return JSONResponse({"status": "ignored"})

        # Strip the 'whatsapp:' prefix Twilio adds to numbers before routing.
        def _strip(n):
            return n[len("whatsapp:"):] if isinstance(n, str) and n.startswith("whatsapp:") else n
        from_number = _strip(from_number)
        to_number = _strip(to_number)

        # Resolve which business owns this destination number (best-effort).
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        business_id = _business_for_phone(sb, to_number)
        if not business_id:
            return JSONResponse({"status": "no_business"})

        # Publish event — autonomous agents handle the rest.
        from backend.events.bus import publish
        await publish(business_id, "whatsapp.received", {
            "from": from_number,
            "to": to_number,
            "body": text[:2000],
            "channel": "whatsapp",
            "direction": "inbound",
        }, source="whatsapp_webhook")

        # Route into the conversational SDR (best-effort — never crash the webhook).
        try:
            from backend.conversations.manager import handle_inbound_whatsapp
            await handle_inbound_whatsapp(business_id, {
                "from": from_number,
                "to": to_number,
                "body": text[:2000],
                "channel": "whatsapp",
                "direction": "inbound",
            })
        except Exception:
            pass

        return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)})
