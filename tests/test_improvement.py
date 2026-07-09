"""
Tests for SAFE CLOSED-LOOP SELF-IMPROVEMENT (backend/engines/improvement_manager.py).

Offline: get_supabase is patched at its source module path
(backend.memory.supabase_client.get_supabase) because improvement_manager
imports it lazily inside each function. Env is monkeypatched per-test so the
AUTO_IMPROVE default-OFF guardrail is exercised.
"""
from unittest.mock import AsyncMock, patch

from backend.engines import improvement_manager

SB_PATH = "backend.memory.supabase_client.get_supabase"
METRIC_PATH = "backend.engines.improvement_manager._read_current_metric"


# ── propose ──────────────────────────────────────────────────────────────
async def test_propose_inserts_proposed_row(make_sb, monkeypatch):
    monkeypatch.delenv("AUTO_IMPROVE", raising=False)
    sb = make_sb(insert_id="imp-1")
    with patch(SB_PATH, return_value=sb):
        imp_id = await improvement_manager.propose(
            "biz-1", "prompt", "cfo", new_value="be concise", rationale="tone",
        )
    assert imp_id == "imp-1"
    row = sb.queries["improvements"].inserted[0]
    assert row["status"] == "proposed"
    assert row["target_type"] == "prompt"
    assert row["target_key"] == "cfo"
    assert row["new_value"] == "be concise"


# ── start_canary gating ──────────────────────────────────────────────────
async def test_start_canary_noop_when_flag_unset(make_sb, monkeypatch):
    monkeypatch.delenv("AUTO_IMPROVE", raising=False)
    sb = make_sb()
    with patch(SB_PATH, return_value=sb):
        ok = await improvement_manager.start_canary("biz-1", "imp-1")
    assert ok is False
    # No DB write attempted -> table never touched for update.
    assert "improvements" not in sb.queries


async def test_start_canary_noop_when_flag_false(make_sb, monkeypatch):
    monkeypatch.setenv("AUTO_IMPROVE", "false")
    sb = make_sb()
    with patch(SB_PATH, return_value=sb):
        ok = await improvement_manager.start_canary("biz-1", "imp-1")
    assert ok is False


async def test_start_canary_sets_status_when_flag_true(make_sb, monkeypatch):
    monkeypatch.setenv("AUTO_IMPROVE", "true")
    sb = make_sb({"improvements": [
        {"id": "imp-1", "target_key": "cfo", "status": "proposed"}
    ]})
    with patch(SB_PATH, return_value=sb), \
         patch(METRIC_PATH, new=AsyncMock(return_value=0.8)):
        ok = await improvement_manager.start_canary("biz-1", "imp-1")
    assert ok is True
    upd = sb.queries["improvements"].updated[0]
    assert upd["status"] == "canary"
    assert upd["metric_baseline"] == 0.8


# ── evaluate_canary ──────────────────────────────────────────────────────
async def test_evaluate_canary_noop_when_flag_off(make_sb, monkeypatch):
    monkeypatch.delenv("AUTO_IMPROVE", raising=False)
    sb = make_sb()
    with patch(SB_PATH, return_value=sb):
        status = await improvement_manager.evaluate_canary("biz-1", "imp-1")
    assert status == "proposed"


async def test_evaluate_canary_adopts_when_metric_holds(make_sb, monkeypatch):
    monkeypatch.setenv("AUTO_IMPROVE", "true")
    monkeypatch.setenv("CANARY_TOLERANCE", "0.05")
    sb = make_sb({"improvements": [
        {"id": "imp-1", "target_key": "cfo", "metric_baseline": 1.0}
    ]})
    # canary >= baseline -> adopt
    with patch(SB_PATH, return_value=sb), \
         patch(METRIC_PATH, new=AsyncMock(return_value=1.2)):
        status = await improvement_manager.evaluate_canary("biz-1", "imp-1")
    assert status == "adopted"
    upd = sb.queries["improvements"].updated[0]
    assert upd["status"] == "adopted"
    assert upd["metric_canary"] == 1.2
    assert upd["decided_at"]


async def test_evaluate_canary_rolls_back_when_worse(make_sb, monkeypatch):
    monkeypatch.setenv("AUTO_IMPROVE", "true")
    monkeypatch.setenv("CANARY_TOLERANCE", "0.05")
    sb = make_sb({"improvements": [
        {"id": "imp-1", "target_key": "cfo", "metric_baseline": 1.0}
    ]})
    # canary well below baseline*(1-tol)=0.95 -> rollback
    with patch(SB_PATH, return_value=sb), \
         patch(METRIC_PATH, new=AsyncMock(return_value=0.5)):
        status = await improvement_manager.evaluate_canary("biz-1", "imp-1")
    assert status == "rolled_back"
    assert sb.queries["improvements"].updated[0]["status"] == "rolled_back"


# ── rollback ─────────────────────────────────────────────────────────────
async def test_rollback_sets_status(make_sb, monkeypatch):
    sb = make_sb()
    with patch(SB_PATH, return_value=sb):
        ok = await improvement_manager.rollback("biz-1", "imp-1")
    assert ok is True
    assert sb.queries["improvements"].updated[0]["status"] == "rolled_back"


# ── DB error safety: never raise, return safe values ─────────────────────
def _raiser(*a, **k):
    raise RuntimeError("db down")


async def test_all_functions_safe_on_db_error(monkeypatch):
    monkeypatch.setenv("AUTO_IMPROVE", "true")
    with patch(SB_PATH, side_effect=_raiser):
        assert await improvement_manager.propose("b", "prompt", "cfo", "x") is None
        assert await improvement_manager.start_canary("b", "imp-1") is False
        # evaluate_canary swallows and returns the safe (rolled_back) outcome
        assert await improvement_manager.evaluate_canary("b", "imp-1") == "rolled_back"
        assert await improvement_manager.rollback("b", "imp-1") is False


async def test_read_current_metric_safe_and_bounded():
    # Now backed by agent_metrics.reliability (which never raises and returns a
    # trusting default): the metric must be a float in [0,1] and never raise.
    val = await improvement_manager._read_current_metric("b", "cfo")
    assert isinstance(val, float) and 0.0 <= val <= 1.0


async def test_apply_adopted_value_writes_reversible_addendum(make_sb):
    sb = make_sb({"businesses": [{"config": {}}]})
    with patch(SB_PATH, return_value=sb):
        improvement_manager._apply_adopted_value(
            "biz-1", {"target_type": "prompt", "target_key": "cfo", "new_value": "Be concise."})
    upd = sb.queries["businesses"].updated[-1]
    assert upd["config"]["prompt_addenda"]["cfo"] == ["Be concise."]


async def test_apply_adopted_value_skips_workflow(make_sb):
    sb = make_sb({"businesses": [{"config": {}}]})
    with patch(SB_PATH, return_value=sb):
        improvement_manager._apply_adopted_value(
            "biz-1", {"target_type": "workflow", "target_key": "wf", "new_value": "y"})
    # workflow improvements are ledger-only -> no config write attempted
    assert "businesses" not in sb.queries


async def test_rollback_removes_addendum(make_sb):
    sb = make_sb({
        "improvements": [{"id": "imp-1", "target_type": "prompt",
                          "target_key": "cfo", "new_value": "Be concise."}],
        "businesses": [{"config": {"prompt_addenda": {"cfo": ["Be concise.", "Keep it warm."]}}}],
    })
    with patch(SB_PATH, return_value=sb):
        ok = await improvement_manager.rollback("biz-1", "imp-1")
    assert ok is True
    updates = sb.queries["businesses"].updated
    assert any(u.get("config", {}).get("prompt_addenda", {}).get("cfo") == ["Keep it warm."]
               for u in updates)



# ── valid_prompt_targets (per-agent targeting) ──────────────────────────────
def test_valid_prompt_targets_contains_core_agents():
    targets = improvement_manager.valid_prompt_targets()
    assert isinstance(targets, set)
    # Works via the fallback set even if prompts/ is absent in the test env.
    assert {"cfo", "coo", "cro", "cmo", "cto", "ceo"}.issubset(targets)


def test_valid_prompt_targets_cached():
    # Second call returns the same content (module-level cache).
    a = improvement_manager.valid_prompt_targets()
    b = improvement_manager.valid_prompt_targets()
    assert a == b
    assert {"cfo", "ceo"}.issubset(b)


# ── _valid_target pure helper ───────────────────────────────────────────────
def test_valid_target_prompt_known():
    assert improvement_manager._valid_target("prompt", "cfo") is True


def test_valid_target_prompt_unknown_skipped():
    assert improvement_manager._valid_target("prompt", "not_a_prompt") is False


def test_valid_target_workflow_always_ok():
    assert improvement_manager._valid_target("workflow", "anything-at-all") is True


def test_valid_target_empty_key_rejected():
    assert improvement_manager._valid_target("prompt", "") is False
    assert improvement_manager._valid_target("workflow", "") is False


# ── _normalize_agent ────────────────────────────────────────────────────────
def test_normalize_agent_class_names():
    assert improvement_manager._normalize_agent("CFOAgent") == "cfo"
    assert improvement_manager._normalize_agent("CustomerSuccessAgent") == "customersuccess"
    assert improvement_manager._normalize_agent("LearningDirectorAgent") == "learning"


# ── _read_current_metric normalized matching ────────────────────────────────
async def test_read_current_metric_matches_normalized_class_name(make_sb, monkeypatch):
    # Two CFOAgent rows (1 success, 1 failure) -> success_rate 0.5 for key "cfo".
    sb = make_sb({"agent_metrics": [
        {"agent_name": "CFOAgent", "success": True},
        {"agent_name": "CFOAgent", "success": False},
    ]})
    with patch(SB_PATH, return_value=sb):
        val = await improvement_manager._read_current_metric("biz-1", "cfo")
    assert abs(val - 0.5) < 1e-9


async def test_read_current_metric_neutral_when_no_rows(make_sb, monkeypatch):
    # No agent_metrics rows at all -> neutral 1.0 (never forces a rollback).
    sb = make_sb({"agent_metrics": []})
    with patch(SB_PATH, return_value=sb):
        val = await improvement_manager._read_current_metric("biz-1", "cfo")
    assert val == 1.0
