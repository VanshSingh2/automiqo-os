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



# ── self-consistency (multi-sample judge for risky actions) ─────────────────
async def test_self_consistency_disagreement_escalates(monkeypatch):
    # Judge ON, high-risk (non-blast-radius) workflow -> samples N times.
    # Disagreeing samples (straddle the 0.5 threshold) -> force escalate.
    # Neutralize the autonomy governor so the JUDGE is the deciding factor.
    monkeypatch.setenv("AUTONOMY_MIN_RUNS", "0")
    monkeypatch.setenv("VERIFY_LLM_JUDGE", "true")
    monkeypatch.setenv("VERIFY_CONSISTENCY_SAMPLES", "3")

    fake = AsyncMock(side_effect=[(0.9, "safe"), (0.1, "risky"), (0.85, "safe")])
    monkeypatch.setattr(verification_engine, "_llm_judge", fake)

    verdict = await verification_engine.evaluate_action(
        "biz-1", "reactivate_dormant_member", {"reason": "dormant 90d"}, "reactivation"
    )
    assert verdict["approved"] is False
    assert verdict["verdict"] in ("escalate", "block")
    assert "judge_disagreement" in verdict["reasons"]
    # The judge was sampled multiple times, not once.
    assert fake.await_count == 3


async def test_self_consistency_low_sample_escalates(monkeypatch):
    # One very-low sample (below 0.15) with no disagreement -> judge_low.
    monkeypatch.setenv("AUTONOMY_MIN_RUNS", "0")
    monkeypatch.setenv("VERIFY_LLM_JUDGE", "true")
    monkeypatch.setenv("VERIFY_CONSISTENCY_SAMPLES", "3")

    fake = AsyncMock(side_effect=[(0.1, "no"), (0.05, "no"), (0.12, "no")])
    monkeypatch.setattr(verification_engine, "_llm_judge", fake)

    verdict = await verification_engine.evaluate_action(
        "biz-1", "reactivate_dormant_member", {"reason": "dormant"}, "reactivation"
    )
    assert verdict["approved"] is False
    assert "judge_low" in verdict["reasons"]


async def test_self_consistency_agreement_allows(monkeypatch):
    # All samples agree it's safe -> use their mean -> allow.
    # Neutralize the autonomy governor (it would otherwise escalate a high-risk
    # workflow with no track record) so the JUDGE agreement is what allows.
    monkeypatch.setenv("AUTONOMY_MIN_RUNS", "0")
    monkeypatch.setenv("VERIFY_LLM_JUDGE", "true")
    monkeypatch.setenv("VERIFY_CONSISTENCY_SAMPLES", "3")

    fake = AsyncMock(side_effect=[(0.9, "ok"), (0.88, "ok"), (0.92, "ok")])
    monkeypatch.setattr(verification_engine, "_llm_judge", fake)

    verdict = await verification_engine.evaluate_action(
        "biz-1", "reactivate_dormant_member", {"reason": "dormant"}, "reactivation"
    )
    assert verdict["verdict"] == "allow"
    assert verdict["approved"] is True
    assert fake.await_count == 3


async def test_low_risk_judge_single_sample(monkeypatch):
    # Low-risk workflow keeps single-call behavior even with sampling configured.
    monkeypatch.setenv("VERIFY_LLM_JUDGE", "true")
    monkeypatch.setenv("VERIFY_CONSISTENCY_SAMPLES", "5")

    fake = AsyncMock(return_value=(0.95, "fine"))
    monkeypatch.setattr(verification_engine, "_llm_judge", fake)

    verdict = await verification_engine.evaluate_action(
        "biz-1", "send_reminder_24h", {"customer_id": "c1", "appointment_id": "a1"}, "reminder"
    )
    assert verdict["verdict"] == "allow"
    assert fake.await_count == 1


# ── grounding check (anti-hallucination on referenced entity ids) ───────────
_REAL_UUID = "12345678-1234-1234-1234-1234567890ab"


async def test_grounding_ungrounded_id_escalates(make_sb, monkeypatch):
    # Real-looking UUID that does NOT exist in the DB -> escalate + reason.
    monkeypatch.setenv("VERIFY_GROUNDING", "true")
    sb = make_sb({"customers": []})  # customers table returns no rows
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        verdict = await verification_engine.evaluate_action(
            "biz-1", "send_reminder_24h", {"customer_id": _REAL_UUID}, "reminder"
        )
    assert verdict["approved"] is False
    assert verdict["verdict"] in ("escalate", "block")
    assert "ungrounded_customer_id" in verdict["reasons"]


async def test_grounding_valid_id_allows(make_sb, monkeypatch):
    # Real-looking UUID that DOES exist -> grounded -> allow.
    monkeypatch.setenv("VERIFY_GROUNDING", "true")
    sb = make_sb({"customers": [{"id": _REAL_UUID}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        verdict = await verification_engine.evaluate_action(
            "biz-1", "send_reminder_24h", {"customer_id": _REAL_UUID}, "reminder"
        )
    assert verdict["verdict"] == "allow"
    assert verdict["approved"] is True
    assert not any("ungrounded" in r for r in verdict["reasons"])


async def test_grounding_skips_dummy_id_allows(make_sb, monkeypatch):
    # Short/dummy ids ("c1"/"a1") are skipped -> existing allow behavior kept,
    # and the DB is never queried for them.
    monkeypatch.setenv("VERIFY_GROUNDING", "true")
    sb = make_sb({"customers": []})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        verdict = await verification_engine.evaluate_action(
            "biz-1", "send_reminder_24h", {"customer_id": "c1", "appointment_id": "a1"}, "reminder"
        )
    assert verdict["verdict"] == "allow"
    assert verdict["approved"] is True
    # Grounding never touched the customers table for a dummy id.
    assert "customers" not in sb.queries


async def test_grounding_disabled_skips_check(make_sb, monkeypatch):
    # VERIFY_GROUNDING=false -> grounding does not run even for a real UUID.
    monkeypatch.setenv("VERIFY_GROUNDING", "false")
    sb = make_sb({"customers": []})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        verdict = await verification_engine.evaluate_action(
            "biz-1", "send_reminder_24h", {"customer_id": _REAL_UUID}, "reminder"
        )
    assert verdict["verdict"] == "allow"
    assert "customers" not in sb.queries
