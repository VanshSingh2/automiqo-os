"""Tests for per-agent accountability metrics + the graduated-autonomy governor.

All offline: Supabase is stubbed via conftest (make_sb). DB access points are
patched at the module level (backend.engines.*.get_supabase), matching the
existing engine-test convention.
"""
from unittest.mock import patch

from backend import obs
from backend.engines import agent_metrics, autonomy_governor


# ── agent_metrics.record ─────────────────────────────────────────────────────
async def test_record_inserts_into_agent_metrics(make_sb):
    sb = make_sb()
    with patch("backend.engines.agent_metrics.get_supabase", return_value=sb):
        await agent_metrics.record(
            "biz-1", "CMOAgent", "agent.run",
            workflow="daily_pulse", latency_ms=120, cost_usd=0.01,
            success=True, trace_id="abc123",
        )
    assert sb.queries["agent_metrics"].inserted, "expected a row inserted into agent_metrics"
    row = sb.queries["agent_metrics"].inserted[0]
    assert row["agent_name"] == "CMOAgent"
    assert row["business_id"] == "biz-1"
    assert row["event"] == "agent.run"
    assert row["workflow"] == "daily_pulse"
    assert row["success"] is True
    assert row["trace_id"] == "abc123"
    assert "created_at" in row


async def test_record_never_raises_on_db_error():
    class _Boom:
        def table(self, *a, **k):
            raise RuntimeError("no table")
    with patch("backend.engines.agent_metrics.get_supabase", return_value=_Boom()):
        # Must not raise despite the DB blowing up.
        await agent_metrics.record("biz-1", "CFOAgent", "agent.run", success=False)


# ── agent_metrics.reliability ────────────────────────────────────────────────
async def test_reliability_defaults_when_table_empty(make_sb):
    sb = make_sb()  # no rows for agent_metrics
    with patch("backend.engines.agent_metrics.get_supabase", return_value=sb):
        out = await agent_metrics.reliability("biz-1", "CMOAgent")
    assert out["runs"] == 0
    assert out["success_rate"] == 1.0
    assert out["avg_latency_ms"] == 0
    assert out["total_cost_usd"] == 0.0


async def test_reliability_computes_success_rate_from_rows(make_sb):
    sb = make_sb({"agent_metrics": [
        {"success": True, "latency_ms": 100, "cost_usd": 0.01},
        {"success": True, "latency_ms": 200, "cost_usd": 0.02},
        {"success": False, "latency_ms": 300, "cost_usd": 0.03},
    ]})
    with patch("backend.engines.agent_metrics.get_supabase", return_value=sb):
        out = await agent_metrics.reliability("biz-1", "CMOAgent")
    assert out["runs"] == 3
    assert round(out["success_rate"], 3) == 0.667
    assert out["avg_latency_ms"] == 200
    assert round(out["total_cost_usd"], 2) == 0.06


async def test_reliability_defaults_on_error():
    class _Boom:
        def table(self, *a, **k):
            raise RuntimeError("boom")
    with patch("backend.engines.agent_metrics.get_supabase", return_value=_Boom()):
        out = await agent_metrics.reliability("biz-1", "CMOAgent")
    assert out == {"runs": 0, "success_rate": 1.0, "avg_latency_ms": 0, "total_cost_usd": 0.0}


# ── autonomy_governor.assess (sync) ──────────────────────────────────────────
def test_assess_new_agent_high_risk_blocks(make_sb):
    sb = make_sb()  # 0 runs
    with patch("backend.engines.autonomy_governor.get_supabase", return_value=sb):
        out = autonomy_governor.assess("biz-1", "issue_refund", risk_level="high")
    assert out["allow_auto"] is False
    assert "insufficient_track_record" in out["reason"]


def test_assess_new_agent_low_risk_allows(make_sb):
    sb = make_sb()  # 0 runs
    with patch("backend.engines.autonomy_governor.get_supabase", return_value=sb):
        out = autonomy_governor.assess("biz-1", "send_email", risk_level="low")
    assert out["allow_auto"] is True


def test_assess_healthy_history_allows(monkeypatch):
    # Plenty of runs, high success -> allowed even for high risk.
    monkeypatch.setattr(autonomy_governor, "_recent_stats", lambda *a, **k: (50, 0.98))
    out = autonomy_governor.assess("biz-1", "issue_refund", risk_level="high")
    assert out["allow_auto"] is True
    assert out["reliability"] == 0.98
    assert out["reason"] == "ok"


def test_assess_low_success_blocks_non_low_risk(monkeypatch):
    monkeypatch.setattr(autonomy_governor, "_recent_stats", lambda *a, **k: (50, 0.5))
    out = autonomy_governor.assess("biz-1", "post_content", risk_level="medium")
    assert out["allow_auto"] is False
    assert "low_success_rate" in out["reason"]


def test_assess_fails_open_on_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(autonomy_governor, "_recent_stats", _boom)
    out = autonomy_governor.assess("biz-1", "wf", risk_level="critical")
    assert out == {"allow_auto": True, "reliability": 1.0, "reason": "governor_failopen"}


# ── autonomy_governor.assess_agent (async) ───────────────────────────────────
async def test_assess_agent_healthy_allows(monkeypatch):
    async def _fake_reliability(*a, **k):
        return {"runs": 20, "success_rate": 0.95, "avg_latency_ms": 100, "total_cost_usd": 1.0}
    monkeypatch.setattr(agent_metrics, "reliability", _fake_reliability)
    out = await autonomy_governor.assess_agent("biz-1", "CMOAgent", risk_level="high")
    assert out["allow_auto"] is True
    assert out["reliability"] == 0.95


async def test_assess_agent_new_agent_high_risk_blocks(monkeypatch):
    async def _fake_reliability(*a, **k):
        return {"runs": 0, "success_rate": 1.0, "avg_latency_ms": 0, "total_cost_usd": 0.0}
    monkeypatch.setattr(agent_metrics, "reliability", _fake_reliability)
    out = await autonomy_governor.assess_agent("biz-1", "NewAgent", risk_level="critical")
    assert out["allow_auto"] is False


# ── obs helpers ──────────────────────────────────────────────────────────────
async def test_record_agent_run_and_trace_id_dont_raise():
    tid = obs.new_trace_id()
    assert isinstance(tid, str) and len(tid) == 12
    # record_agent_run forwards to agent_metrics.record — must never raise.
    await obs.record_agent_run("biz-1", "CMOAgent", tid, 123, True, cost_usd=0.02, workflow="wf")


def test_now_ms_and_timed_are_monotonic():
    start = obs.now_ms()
    assert isinstance(start, int)
    with obs.timed() as t:
        pass
    assert t.ms >= 0


# ── base_agent helper ────────────────────────────────────────────────────────
async def test_base_agent_record_run_does_not_raise():
    from agents.base_agent import BaseAgent

    class _Agent(BaseAgent):
        async def run(self, question, context=None):
            return None

    agent = _Agent(business_id="biz-1")
    start = obs.now_ms()
    await agent._record_run("trace-xyz", start, True, workflow="daily_pulse")
