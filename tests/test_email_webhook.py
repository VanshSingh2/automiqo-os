"""Tests for the inbound email intake webhook (/webhooks/email/inbound).

Runs fully offline: the webhooks router is mounted on a throwaway FastAPI app
so main.py's heavy lifespan never starts. Supabase is stubbed via make_sb and
the event-bus publish is patched (it's imported lazily inside the handler, like
the SMS webhook, so we patch it at its source module).
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


def test_inbound_email_publishes_event(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {"support_email": "support@biz.com"}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub:
        r = _client().post("/webhooks/email/inbound", json={
            "from": "a@x.com",
            "to": "support@biz.com",
            "subject": "Help",
            "text": "my appointment",
        })
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert pub.await_count == 1
    args, kwargs = pub.call_args
    # publish(business_id, "email.received", {...}, source="email_webhook")
    assert args[0] == "biz-1"
    assert args[1] == "email.received"
    assert args[2]["from"] == "a@x.com"
    assert args[2]["channel"] == "email"
    assert args[2]["direction"] == "inbound"


def test_missing_from_or_text_is_ignored(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub:
        # Missing text
        r1 = _client().post("/webhooks/email/inbound", json={"from": "a@x.com"})
        # Missing from
        r2 = _client().post("/webhooks/email/inbound", json={"text": "hello"})
    assert r1.json() == {"status": "ignored"}
    assert r2.json() == {"status": "ignored"}
    assert pub.await_count == 0


def test_bad_or_missing_signature_returns_401(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {}}]})
    payload = {"from": "a@x.com", "to": "support@biz.com", "text": "hi"}
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch.dict("os.environ", {"EMAIL_WEBHOOK_SECRET": "shhh"}):
        # No signature header at all
        r_missing = _client().post("/webhooks/email/inbound", json=payload)
        # Wrong signature
        r_bad = _client().post(
            "/webhooks/email/inbound",
            json=payload,
            headers={"x-email-signature-256": "deadbeef"},
        )
    assert r_missing.status_code == 401
    assert r_bad.status_code == 401
    assert pub.await_count == 0


def test_correct_signature_returns_200(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-1", "config": {"support_email": "support@biz.com"}}]})
    payload = {"from": "a@x.com", "to": "support@biz.com", "subject": "Help", "text": "my appointment"}
    # TestClient serializes json with compact separators; replicate exactly for the HMAC.
    raw = json.dumps(payload).encode()
    secret = "shhh"
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.events.bus.publish", new=AsyncMock()) as pub, \
         patch.dict("os.environ", {"EMAIL_WEBHOOK_SECRET": secret}):
        r = _client().post(
            "/webhooks/email/inbound",
            content=raw,
            headers={"x-email-signature-256": sig, "content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert pub.await_count == 1


def test_router_subscribes_coo_to_email_received():
    import backend.events.router as event_router
    assert "coo" in event_router.get_handlers("email.received")
