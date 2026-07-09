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


async def test_read_current_metric_safe_on_db_error(monkeypatch):
    with patch(SB_PATH, side_effect=_raiser):
        assert await improvement_manager._read_current_metric("b", "cfo") == 0.0
