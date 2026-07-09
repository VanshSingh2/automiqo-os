"""Offline tests for the Slack integration routing + signature logic."""
import hashlib
import hmac
import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import slack


def _client():
    app = FastAPI()
    app.include_router(slack.router)
    return TestClient(app)


# ── url_verification handshake ──────────────────────────────────────────────
def test_url_verification_returns_challenge():
    r = _client().post("/webhooks/slack/events",
                       json={"type": "url_verification", "challenge": "abc123"})
    assert r.status_code == 200
    assert r.json()["challenge"] == "abc123"


# ── agent routing ───────────────────────────────────────────────────────────
def test_resolve_agent_key_mention_dept_head():
    key, text = slack.resolve_agent_key("@cfo what is revenue?", {})
    assert key == "cfo"
    assert text == "what is revenue?"


def test_resolve_agent_key_manager_by_name():
    key, _ = slack.resolve_agent_key("@Inventory Manager check stock", {})
    assert key == "coo.inventory"


def test_resolve_agent_key_colon_form():
    key, text = slack.resolve_agent_key("cmo: draft a promo", {})
    assert key == "cmo"
    assert text == "draft a promo"


def test_resolve_agent_key_channel_map():
    cfg = {"slack_agent_map": {"C999": "cro.upsell"}}
    key, _ = slack.resolve_agent_key("hey", cfg, channel="C999")
    assert key == "cro.upsell"


def test_resolve_agent_key_defaults_to_ceo():
    key, _ = slack.resolve_agent_key("just a general question", {})
    assert key == "ceo"


# ── signature verification ──────────────────────────────────────────────────
def test_signature_skipped_when_no_secret(monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)

    class _Req:
        headers = {}
    assert slack._verify_signature(_Req(), b"{}") is True


def test_signature_valid_and_invalid(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "shh")
    raw = b'{"type":"event_callback"}'
    ts = str(int(time.time()))
    good = "v0=" + hmac.new(b"shh", f"v0:{ts}:{raw.decode()}".encode(), hashlib.sha256).hexdigest()

    class _Req:
        def __init__(self, sig):
            self.headers = {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}

    assert slack._verify_signature(_Req(good), raw) is True
    assert slack._verify_signature(_Req("v0=deadbeef"), raw) is False


async def test_post_to_slack_noop_without_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert await slack.post_to_slack("C1", "hi") is False
