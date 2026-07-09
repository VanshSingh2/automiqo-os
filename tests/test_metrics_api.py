"""Accountability metrics API tests (offline).

The router is mounted on a throwaway FastAPI app + TestClient so main.py's heavy
lifespan never starts. ``get_supabase`` is patched with the ``make_sb`` fixture.

Note: the FakeSupabase in conftest ignores filters and returns each table's rows
as-is, so assertions are designed around distinct-agent extraction over the
returned rows rather than server-side filtering.
"""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


_ROWS = [
    {"agent_name": "CFOAgent", "event": "run", "workflow": "pnl",
     "latency_ms": 100, "cost_usd": 0.01, "success": True, "trace_id": "t1",
     "created_at": "2099-01-01T00:00:00+00:00"},
    {"agent_name": "CMOAgent", "event": "run", "workflow": "campaign",
     "latency_ms": 200, "cost_usd": 0.02, "success": False, "trace_id": "t2",
     "created_at": "2099-01-02T00:00:00+00:00"},
    {"agent_name": "CFOAgent", "event": "run", "workflow": "tax",
     "latency_ms": 150, "cost_usd": 0.03, "success": True, "trace_id": "t3",
     "created_at": "2099-01-03T00:00:00+00:00"},
]


def _patch_sb(sb):
    """Patch every get_supabase reference used by the metrics endpoints."""
    return [
        patch("backend.memory.supabase_client.get_supabase", return_value=sb),
        patch("backend.engines.agent_metrics.get_supabase", return_value=sb),
    ]


def test_agents_rollup_non_empty(make_sb):
    from backend.api import metrics_api
    sb = make_sb({"agent_metrics": _ROWS})
    patches = _patch_sb(sb)
    for p in patches:
        p.start()
    try:
        r = _client(metrics_api.router).get("/accountability/biz-1/agents")
    finally:
        for p in patches:
            p.stop()

    assert r.status_code == 200
    body = r.json()
    assert body["window_days"] == 14
    assert isinstance(body["agents"], list)
    assert len(body["agents"]) > 0
    for item in body["agents"]:
        assert set(item.keys()) == {
            "agent_name", "runs", "success_rate", "avg_latency_ms", "total_cost_usd"
        }
    # distinct agent extraction over returned rows -> CFOAgent + CMOAgent
    names = {a["agent_name"] for a in body["agents"]}
    assert {"CFOAgent", "CMOAgent"}.issubset(names)


def test_summary_shape_and_types(make_sb):
    from backend.api import metrics_api
    sb = make_sb({"agent_metrics": _ROWS})
    patches = _patch_sb(sb)
    for p in patches:
        p.start()
    try:
        r = _client(metrics_api.router).get("/accountability/biz-1/summary")
    finally:
        for p in patches:
            p.stop()

    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "total_runs", "overall_success_rate", "total_cost_usd",
        "avg_latency_ms", "agent_count", "window_days",
    }
    assert isinstance(body["total_runs"], int)
    assert isinstance(body["overall_success_rate"], (int, float))
    assert isinstance(body["total_cost_usd"], (int, float))
    assert isinstance(body["avg_latency_ms"], (int, float))
    assert isinstance(body["agent_count"], int)
    assert body["total_runs"] == len(_ROWS)


def test_recent_returns_list(make_sb):
    from backend.api import metrics_api
    sb = make_sb({"agent_metrics": _ROWS})
    patches = _patch_sb(sb)
    for p in patches:
        p.start()
    try:
        r = _client(metrics_api.router).get("/accountability/biz-1/recent?limit=10")
    finally:
        for p in patches:
            p.stop()

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == len(_ROWS)


def test_empty_db_returns_zeros(make_sb):
    from backend.api import metrics_api
    sb = make_sb()  # no tables -> agent_metrics missing -> []
    patches = _patch_sb(sb)
    for p in patches:
        p.start()
    try:
        client = _client(metrics_api.router)
        agents = client.get("/accountability/biz-1/agents")
        summary = client.get("/accountability/biz-1/summary")
        recent = client.get("/accountability/biz-1/recent")
    finally:
        for p in patches:
            p.stop()

    assert agents.status_code == 200
    assert agents.json()["agents"] == []

    assert summary.status_code == 200
    s = summary.json()
    assert s["total_runs"] == 0
    assert s["total_cost_usd"] == 0.0
    assert s["agent_count"] == 0

    assert recent.status_code == 200
    assert recent.json() == []
