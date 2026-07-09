"""Tests for the production-hardening features:
webhook signature verification, dispatch idempotency, CEO policy gate, obs logging.
"""
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import HTTPException

from backend.api import webhooks
from backend import obs


# ── obs (structured logging) ────────────────────────────────────────────────
def test_get_logger_and_log_event_never_raise():
    log = obs.get_logger("test.logger")
    obs.log_event(log, "unit.test", business_id="b1", n=3, obj={"k": "v"})


def test_new_trace_id_is_short_hex():
    tid = obs.new_trace_id()
    assert len(tid) == 12
    int(tid, 16)  # valid hex


# ── webhook signature verification ──────────────────────────────────────────
def _req(headers=None):
    return SimpleNamespace(headers=headers or {})


def test_vapi_skips_without_secret(monkeypatch):
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET", raising=False)
    webhooks._verify_vapi(_req())  # no raise


def test_vapi_accepts_correct_secret(monkeypatch):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "s3cret")
    webhooks._verify_vapi(_req({"x-vapi-secret": "s3cret"}))  # no raise


def test_vapi_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "s3cret")
    with pytest.raises(HTTPException) as e:
        webhooks._verify_vapi(_req({"x-vapi-secret": "nope"}))
    assert e.value.status_code == 401


def test_calcom_accepts_valid_hmac(monkeypatch):
    monkeypatch.setenv("CAL_WEBHOOK_SECRET", "whsec")
    raw = b'{"triggerEvent":"BOOKING_CREATED"}'
    sig = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    webhooks._verify_calcom(_req({"x-cal-signature-256": sig}), raw)  # no raise


def test_calcom_rejects_bad_hmac(monkeypatch):
    monkeypatch.setenv("CAL_WEBHOOK_SECRET", "whsec")
    with pytest.raises(HTTPException) as e:
        webhooks._verify_calcom(_req({"x-cal-signature-256": "bad"}), b"{}")
    assert e.value.status_code == 401


def test_telnyx_skips_without_key(monkeypatch):
    monkeypatch.delenv("TELNYX_PUBLIC_KEY", raising=False)
    webhooks._verify_telnyx(_req(), b"{}")  # graceful skip, no raise



# ── multi-tenant routing helper ─────────────────────────────────────────────
def test_business_for_phone_returns_match(make_sb):
    sb = make_sb({"businesses": [{"id": "biz-9", "config": {}}]})
    assert webhooks._business_for_phone(sb, "+15551234567") == "biz-9"


def test_business_for_phone_none_when_empty(make_sb):
    sb = make_sb({"businesses": []})
    assert webhooks._business_for_phone(sb, "+1555") is None


# ── dispatch idempotency ────────────────────────────────────────────────────
from backend.events import handlers


def test_dedup_key_is_deterministic():
    a = handlers._dedup_key("b1", "send_reminder_24h", {"x": 1, "y": 2})
    b = handlers._dedup_key("b1", "send_reminder_24h", {"y": 2, "x": 1})
    c = handlers._dedup_key("b1", "send_reminder_24h", {"x": 9})
    assert a == b        # order-independent
    assert a != c        # different params -> different key


def test_already_dispatched_detects_match(make_sb):
    key = handlers._dedup_key("b1", "send_reminder_24h", {"x": 1})
    sb = make_sb({"tasks": [{"id": "t1", "parameters": {"_idem": key}}]})
    assert handlers._already_dispatched(sb, "b1", "send_reminder_24h", key) is True
    assert handlers._already_dispatched(sb, "b1", "send_reminder_24h", "other") is False


async def test_dispatch_action_dedupes_duplicate(make_sb):
    params = {"appointment_id": "a1"}
    key = handlers._dedup_key("b1", "send_reminder_24h", params)
    sb = make_sb({"tasks": [{"id": "t1", "parameters": {"_idem": key}}]})
    with patch("backend.events.handlers.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=AsyncMock()) as enq:
        await handlers.dispatch_action("b1", "send_reminder_24h", params, "dup")
    enq.assert_not_called()  # duplicate within window -> skipped


async def test_dispatch_action_sets_idem_on_first_fire(make_sb):
    sb = make_sb()  # no existing tasks -> not a duplicate
    with patch("backend.events.handlers.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=AsyncMock()) as enq:
        await handlers.dispatch_action("b1", "send_reminder_24h", {"a": 1}, "first")
    enq.assert_awaited_once()
    assert "_idem" in enq.await_args.args[0]["parameters"]


# ── CEO dispatch routes through the policy gate ─────────────────────────────
def _ceo_tool(name):
    from uuid import uuid4
    from agents.executive.ceo.tools import make_ceo_tools
    for t in make_ceo_tools(uuid4()):
        if getattr(t, "__name__", "") == name:
            return t
    raise AssertionError(f"tool {name} not found")


async def test_ceo_direct_dispatch_goes_through_gate():
    tool = _ceo_tool("dispatch_workflow_directly")
    with patch("backend.events.handlers.dispatch_action", new=AsyncMock()) as da:
        out = await tool("send_sms_campaign", {"msg": "hi"})
    da.assert_awaited_once()
    assert out["dispatched"] is True
    assert out["routed_via"] == "policy_gate"
