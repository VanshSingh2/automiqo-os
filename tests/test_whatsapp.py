"""Tests for the inbound WhatsApp intake webhook (/webhooks/whatsapp/inbound).

Runs fully offline: the webhooks router is mounted on a throwaway FastAPI app
so main.py's heavy lifespan never starts. Supabase is stubbed via make_sb, the
event-bus publish is patched at its source module, and the conversational SDR
entrypoint (handle_inbound_whatsapp) is patched so no LLM/network is touched.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    from backend.api.webhooks import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_inbound_whatsapp_publishes_event(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {"phone": "+15551230000"}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch("backend.conversations.manager.handle_inbound_whatsapp", new=AsyncMock()) as sdr:
        r = _client().post("/webhooks/whatsapp/inbound", json={
            "From": "whatsapp:+15559876543",
            "To": "whatsapp:+15551230000",
            "Body": "do you have any openings this week?",
        })
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert pub.await_count == 1
    args, kwargs = pub.call_args
    # publish(business_id, "whatsapp.received", {...}, source="whatsapp_webhook")
    assert args[0] == "biz-1"
    assert args[1] == "whatsapp.received"
    assert args[2]["from"] == "+15559876543"  # 'whatsapp:' prefix stripped
    assert args[2]["to"] == "+15551230000"
    assert args[2]["channel"] == "whatsapp"
    assert args[2]["direction"] == "inbound"
    assert kwargs.get("source") == "whatsapp_webhook"
    # Routed into the conversational SDR.
    assert sdr.await_count == 1


def test_missing_from_or_text_is_ignored(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch("backend.conversations.manager.handle_inbound_whatsapp", new=AsyncMock()):
        # Missing text/body
        r1 = _client().post("/webhooks/whatsapp/inbound", json={"From": "whatsapp:+15559876543"})
        # Missing from
        r2 = _client().post("/webhooks/whatsapp/inbound", json={"Body": "hello"})
    assert r1.json() == {"status": "ignored"}
    assert r2.json() == {"status": "ignored"}
    assert pub.await_count == 0


def test_bad_signature_returns_401(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {}}]})
    payload = {"From": "whatsapp:+15559876543", "To": "whatsapp:+15551230000", "Body": "hi"}
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch("backend.conversations.manager.handle_inbound_whatsapp", new=AsyncMock()), \
         patch.dict("os.environ", {"WHATSAPP_WEBHOOK_SECRET": "shhh"}):
        # No signature header at all
        r_missing = _client().post("/webhooks/whatsapp/inbound", json=payload)
        # Wrong signature
        r_bad = _client().post(
            "/webhooks/whatsapp/inbound",
            json=payload,
            headers={"x-whatsapp-signature-256": "deadbeef"},
        )
    assert r_missing.status_code == 401
    assert r_bad.status_code == 401
    assert pub.await_count == 0


def test_correct_signature_returns_200(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {"phone": "+15551230000"}}]})
    payload = {"From": "whatsapp:+15559876543", "To": "whatsapp:+15551230000", "Body": "hi there"}
    # TestClient serializes json with compact separators; replicate exactly for the HMAC.
    raw = json.dumps(payload).encode()
    secret = "shhh"
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch("backend.conversations.manager.handle_inbound_whatsapp", new=AsyncMock()), \
         patch.dict("os.environ", {"WHATSAPP_WEBHOOK_SECRET": secret}):
        r = _client().post(
            "/webhooks/whatsapp/inbound",
            content=raw,
            headers={"x-whatsapp-signature-256": sig, "content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert pub.await_count == 1


def test_meta_cloud_api_shape(make_sb):
    """Meta Cloud API nests the message under messages[0].{from,text.body}."""
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch("backend.conversations.manager.handle_inbound_whatsapp", new=AsyncMock()):
        r = _client().post("/webhooks/whatsapp/inbound", json={
            "messages": [{"from": "15559876543", "text": {"body": "interested!"}}],
        })
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert pub.await_count == 1
    assert pub.call_args[0][2]["body"] == "interested!"


def test_router_subscribes_coo_to_whatsapp_received():
    import backend.events.router as event_router
    assert "coo" in event_router.get_handlers("whatsapp.received")
