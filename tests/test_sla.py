"""Tests for the SLA / escalation-timer engine (backend.engines.sla_monitor).

Offline & deterministic: uses the conftest `make_sb` fake Supabase and patches
the lazy `get_supabase` import path used inside sla_monitor
(backend.memory.supabase_client.get_supabase). The fake ignores query filters
and returns rows as-is, so the engine's own created_at age check is what decides
staleness.
"""
from unittest.mock import patch

from backend.engines import sla_monitor

# A timestamp far in the past — always older than any SLA threshold.
_ANCIENT = "2000-01-01T00:00:00+00:00"


async def test_sweep_escalates_stale_pending_recommendations(make_sb):
    sb = make_sb({
        "recommendations": [
            {"id": "r1", "title": "X", "status": "pending",
             "priority": "normal", "created_at": _ANCIENT},
        ],
        "tasks": [],
    })
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = await sla_monitor.sweep("biz-1")

    # A stale recommendation was found and escalated.
    assert result["stale_recommendations"] >= 1
    assert result["escalated"] >= 1

    # An internal notification was logged.
    assert "notifications_log" in sb.queries
    inserted = sb.queries["notifications_log"].inserted
    assert inserted and "SLA" in inserted[0]["message"]

    # The recommendation was bumped to high priority.
    assert "recommendations" in sb.queries
    updated = sb.queries["recommendations"].updated
    assert updated and updated[0].get("priority") == "high"


async def test_sweep_marks_long_stuck_tasks_failed(make_sb):
    sb = make_sb({
        "recommendations": [],
        "tasks": [
            {"id": "t1", "workflow": "send_reminder_24h", "status": "queued",
             "created_at": _ANCIENT},
        ],
    })
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = await sla_monitor.sweep("biz-1")

    # The stuck task was detected.
    assert result["stuck_tasks"] >= 1

    # Beyond 4x the threshold it is force-failed with error='sla_timeout'.
    assert "tasks" in sb.queries
    updated = sb.queries["tasks"].updated
    assert updated
    assert updated[0].get("status") == "failed"
    assert updated[0].get("error") == "sla_timeout"


async def test_sweep_returns_zeros_and_does_not_raise_when_supabase_raises():
    def _boom(*a, **k):
        raise RuntimeError("no db")

    with patch("backend.memory.supabase_client.get_supabase", side_effect=_boom):
        result = await sla_monitor.sweep("biz-1")

    assert result == {"stale_recommendations": 0, "stuck_tasks": 0, "escalated": 0}


async def test_sweep_all_aggregates_across_businesses(make_sb):
    sb = make_sb({
        "businesses": [{"id": "biz-1"}],
        "recommendations": [],
        "tasks": [],
    })
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = await sla_monitor.sweep_all()

    assert result["businesses"] >= 1
    assert result["stale_recommendations"] == 0
    assert result["stuck_tasks"] == 0
