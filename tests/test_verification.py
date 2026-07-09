"""Tests for the pre-execution verification / eval gate.

Deterministic and offline: the LLM judge stays disabled (VERIFY_LLM_JUDGE unset)
and the autonomy governor module is intentionally absent, so evaluate_action
relies purely on the cheap rule checks.
"""
from unittest.mock import patch, AsyncMock

from backend.engines import verification_engine
from backend.events import handlers


# ── evaluate_action: rule checks ────────────────────────────────────────────
async def test_high_blast_radius_escalates():
    verdict = await verification_engine.evaluate_action(
        "biz-1", "send_sms_campaign", {"customer_id": "c1", "message": "hi"}, "campaign"
    )
    assert verdict["verdict"] == "escalate"
    assert verdict["approved"] is False
    assert "high_blast_radius" in verdict["reasons"]


async def test_normal_low_risk_action_allows():
    verdict = await verification_engine.evaluate_action(
        "biz-1", "send_reminder_24h",
        {"customer_id": "c1", "appointment_id": "a1"}, "24h reminder"
    )
    assert verdict["verdict"] == "allow"
    assert verdict["approved"] is True
    assert verdict["score"] >= 0.5


async def test_empty_workflow_escalates():
    verdict = await verification_engine.evaluate_action("biz-1", "", {}, "")
    assert verdict["verdict"] == "escalate"
    assert verdict["approved"] is False
    assert "empty_workflow" in verdict["reasons"]


async def test_unknown_workflow_escalates():
    verdict = await verification_engine.evaluate_action(
        "biz-1", "totally_unknown_workflow_xyz", {"foo": "bar"}, ""
    )
    assert verdict["verdict"] == "escalate"
    assert "unknown_workflow" in verdict["reasons"]


async def test_oversized_parameters_escalate():
    big = {"blob": "x" * 9000}
    verdict = await verification_engine.evaluate_action(
        "biz-1", "send_reminder_24h", {"customer_id": "c1", **big}, ""
    )
    assert verdict["verdict"] == "escalate"
    assert "oversized_parameters" in verdict["reasons"]


async def test_fail_closed_env(monkeypatch):
    # Force an internal error by passing a workflow object that breaks .strip()
    # via monkeypatching _is_known_workflow to raise, while fail-closed is on.
    monkeypatch.setenv("VERIFY_FAIL_CLOSED", "true")

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(verification_engine, "_env_float", _boom)
    verdict = await verification_engine.evaluate_action("biz-1", "send_reminder_24h", {"customer_id": "c"}, "")
    assert verdict["verdict"] == "escalate"
    assert verdict["approved"] is False


# ── dispatch_action integration ─────────────────────────────────────────────
async def test_dispatch_holds_for_review_when_escalated(make_sb, monkeypatch):
    # Threshold above 1.0 => every score escalates.
    monkeypatch.setenv("VERIFY_ESCALATE_THRESHOLD", "1.1")
    sb = make_sb()
    with patch("backend.events.handlers.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=AsyncMock()) as enq:
        await handlers.dispatch_action("biz-1", "send_reminder_24h",
                                       {"customer_id": "c1", "appointment_id": "a1"}, "reminder")
    # Held: a recommendations row inserted, task NOT enqueued.
    assert "recommendations" in sb.queries
    inserted = sb.queries["recommendations"].inserted
    assert inserted and inserted[0]["title"] == "Verify-hold: send_reminder_24h"
    enq.assert_not_called()


async def test_dispatch_fires_when_allowed(make_sb, monkeypatch):
    # Threshold 0 => nothing escalates on score alone; low-risk workflow allows.
    monkeypatch.setenv("VERIFY_ESCALATE_THRESHOLD", "0")
    sb = make_sb()
    with patch("backend.events.handlers.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=AsyncMock()) as enq:
        await handlers.dispatch_action("biz-1", "send_reminder_24h",
                                       {"customer_id": "c1", "appointment_id": "a1"}, "reminder")
    assert "tasks" in sb.queries
    assert sb.queries["tasks"].inserted
    enq.assert_awaited_once()
    assert enq.await_args.args[0]["workflow"] == "send_reminder_24h"


async def test_dispatch_fires_when_verification_raises(make_sb, monkeypatch):
    # If evaluate_action itself raises, dispatch must fail-open and fire.
    async def _boom(*a, **k):
        raise RuntimeError("verify exploded")

    monkeypatch.setattr(verification_engine, "evaluate_action", _boom)
    sb = make_sb()
    with patch("backend.events.handlers.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=AsyncMock()) as enq:
        await handlers.dispatch_action("biz-1", "send_reminder_24h",
                                       {"customer_id": "c1"}, "reminder")
    enq.assert_awaited_once()



# ── LLM judge (now ON by default in production) ─────────────────────────────
async def test_llm_judge_runs_when_enabled(monkeypatch):
    # Enable the judge (conftest disables it globally for speed) and stub the
    # actual LLM call to a low score -> the judge must drag the verdict down.
    monkeypatch.setenv("VERIFY_LLM_JUDGE", "true")

    async def _fake_judge(*a, **k):
        return 0.1, "looks risky"

    monkeypatch.setattr(verification_engine, "_llm_judge", _fake_judge)
    verdict = await verification_engine.evaluate_action(
        "biz-1", "send_reminder_24h", {"customer_id": "c1", "appointment_id": "a1"}, "reminder")
    assert verdict["approved"] is False
    assert verdict["verdict"] in ("escalate", "block")
    assert any("llm_judge" in r for r in verdict["reasons"])


async def test_llm_judge_high_score_allows(monkeypatch):
    monkeypatch.setenv("VERIFY_LLM_JUDGE", "true")

    async def _fake_judge(*a, **k):
        return 0.95, "fine"

    monkeypatch.setattr(verification_engine, "_llm_judge", _fake_judge)
    verdict = await verification_engine.evaluate_action(
        "biz-1", "send_reminder_24h", {"customer_id": "c1", "appointment_id": "a1"}, "reminder")
    assert verdict["verdict"] == "allow"
    assert verdict["approved"] is True
