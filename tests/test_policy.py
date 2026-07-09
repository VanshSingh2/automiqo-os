"""Tests for policy_engine + event router approval/subscription logic."""
from unittest.mock import patch

from backend.engines.policy_engine import policy, POLICIES
from backend.events import router as evt_router


# ── policy_engine ───────────────────────────────────────────────────────────
def test_low_risk_action_auto_approved():
    r = policy.check("send_reminder_24h")
    assert r.risk_level == "low"
    assert r.auto_approved is True
    assert r.requires_approval is False


def test_high_risk_requires_owner_approval():
    r = policy.check("send_sms_campaign")
    assert r.risk_level == "high"
    assert r.auto_approved is False
    assert r.requires_approval is True


def test_critical_action_requires_approval():
    r = policy.check("execute_deployment")
    assert r.risk_level == "critical"
    assert r.requires_approval is True


def test_unknown_action_defaults_to_approval():
    r = policy.check("some_unknown_workflow_xyz")
    assert r.requires_approval is True
    assert r.policy_name == "default_unknown"
    assert r.risk_level == "medium"


def test_is_auto_helper():
    assert policy.is_auto("tag_customer") is True
    assert policy.is_auto("send_email_campaign") is False


def test_risk_level_helper():
    assert policy.risk_level("place_inventory_order") == "high"
    assert policy.risk_level("unknown") == "medium"


def test_business_override_flips_auto_approve():
    sb_data = {"businesses": [{"config": {
        "policy_overrides": {"send_sms_campaign": {"auto_approve": True, "requires_owner": False}}
    }}]}
    from tests.conftest import FakeSupabase
    with patch("backend.engines.policy_engine.get_supabase",
               return_value=FakeSupabase(sb_data)):
        r = policy.check("send_sms_campaign", {}, business_id="biz-1")
    assert r.auto_approved is True
    assert r.requires_approval is False


def test_all_policies_have_valid_risk_levels():
    valid = {"low", "medium", "high", "critical"}
    for action, (risk, auto, owner) in POLICIES.items():
        assert risk in valid, f"{action} has bad risk {risk}"
        assert isinstance(auto, bool) and isinstance(owner, bool)



# ── event router: requires_approval ─────────────────────────────────────────
def test_auto_fire_actions_do_not_require_approval():
    for action in ["send_reminder_24h", "recover_missed_call", "log_no_show",
                   "score_conversation", "request_google_review"]:
        assert evt_router.requires_approval(action) is False, action


def test_approval_required_actions():
    for action in ["send_sms_campaign", "send_email_campaign", "book_appointment",
                   "send_payment_link", "send_cold_outreach"]:
        assert evt_router.requires_approval(action) is True, action


def test_unknown_action_requires_approval_by_default():
    assert evt_router.requires_approval("totally_unknown_action") is True


# ── event router: subscriptions / fan-out ───────────────────────────────────
def test_get_handlers_fans_out_to_multiple_depts():
    from backend.events.bus import E
    handlers = evt_router.get_handlers(E.APPT_COMPLETED)
    assert set(handlers) == {"csd", "cro", "cfo"}


def test_get_handlers_unknown_event_returns_empty():
    assert evt_router.get_handlers("no.such.event") == []


def test_negative_review_alerts_ceo():
    from backend.events.bus import E
    assert "ceo" in evt_router.get_handlers(E.REVIEW_NEGATIVE)


def test_router_and_policy_agree_on_campaign_gating():
    # Both gates must agree that campaigns need approval (no divergence).
    assert evt_router.requires_approval("send_sms_campaign") is True
    assert policy.check("send_sms_campaign").requires_approval is True
