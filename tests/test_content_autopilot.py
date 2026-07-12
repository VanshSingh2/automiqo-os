"""Offline tests for the Content Autopilot (feature #9).

No network / no SDKs: the shared conftest stubs supabase + langchain, and the
dept LLM is patched to return fixed STRICT-JSON so generation is deterministic.
Covers:
  * generate_calendar parses LLM JSON into posts
  * generate_calendar is defensive (bad JSON -> empty posts, never raises)
  * schedule_calendar stages rows into content_posts + returns the count
  * the API router mounts on a throwaway app and returns 200
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.base_agent import BaseAgent


_CALENDAR_JSON = json.dumps({
    "posts": [
        {"day": 1, "platform": "instagram", "format": "reel",
         "hook": "Big news", "caption": "Come see us!", "hashtags": ["#local", "#spa"], "cta": "Book now"},
        {"day": 2, "platform": "tiktok", "format": "short",
         "hook": "Behind the scenes", "caption": "How we work", "hashtags": "#bts #fun", "cta": "Follow"},
        {"day": 3, "platform": "linkedin", "format": "post",
         "hook": "Why quality matters", "caption": "Our promise", "hashtags": [], "cta": "Learn more"},
    ]
})


def _fake_llm(content):
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content=content))
    return llm


# ── generate_calendar ────────────────────────────────────────────────────────
async def test_generate_calendar_parses_llm_posts(make_sb):
    from backend.integrations import content_autopilot
    sb = make_sb({"businesses": [{"name": "Glow Spa", "industry": "med spa",
                                  "config": {"brand_voice": "warm", "services": [{"name": "Facial"}]}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm(_CALENDAR_JSON)):
        out = await content_autopilot.generate_calendar("biz-1", days=3,
                                                         platforms=["instagram", "tiktok", "linkedin"])
    assert out["days"] == 3
    assert len(out["posts"]) == 3
    first = out["posts"][0]
    assert first["platform"] == "instagram"
    assert first["hashtags"] == ["#local", "#spa"]
    assert first["cta"] == "Book now"
    # string hashtags get normalized to a list
    assert out["posts"][1]["hashtags"] == ["#bts", "#fun"]


async def test_generate_calendar_defaults_platforms(make_sb):
    from backend.integrations import content_autopilot
    sb = make_sb({"businesses": [{"name": "Biz", "industry": "service", "config": {}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm(_CALENDAR_JSON)):
        out = await content_autopilot.generate_calendar("biz-1")
    assert out["days"] == 7
    assert len(out["posts"]) == 3


async def test_generate_calendar_defensive_on_bad_json(make_sb):
    from backend.integrations import content_autopilot
    sb = make_sb({"businesses": []})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm("not json at all")):
        out = await content_autopilot.generate_calendar("biz-1", days=5)
    assert out == {"days": 5, "posts": []}


async def test_generate_calendar_never_raises_on_llm_error():
    from backend.integrations import content_autopilot
    boom = MagicMock()
    boom.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch.object(BaseAgent, "_build_dept_llm", return_value=boom):
        out = await content_autopilot.generate_calendar("biz-1", days=4)
    assert out == {"days": 4, "posts": []}


# ── schedule_calendar ──────────────────────────────────────────────────────────
async def test_schedule_calendar_inserts_into_content_posts(make_sb):
    from backend.integrations import content_autopilot
    sb = make_sb()
    posts = [
        {"day": 1, "platform": "instagram", "caption": "one"},
        {"day": 2, "platform": "tiktok", "caption": "two"},
    ]
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        out = await content_autopilot.schedule_calendar("biz-1", posts)
    assert out == {"scheduled": 2}
    assert "content_posts" in sb.queries
    inserted = sb.queries["content_posts"].inserted
    assert len(inserted) == 2
    row = inserted[0]
    assert row["business_id"] == "biz-1"
    assert row["platform"] == "instagram"
    assert row["status"] == "scheduled"
    assert "scheduled_for" in row and "created_at" in row


async def test_schedule_calendar_empty_returns_zero():
    from backend.integrations import content_autopilot
    out = await content_autopilot.schedule_calendar("biz-1", [])
    assert out == {"scheduled": 0}


# ── API router ───────────────────────────────────────────────────────────────
def _client():
    from backend.api.content_api import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_calendar_endpoint_returns_200(make_sb):
    sb = make_sb({"businesses": [{"name": "Biz", "industry": "service", "config": {}}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm(_CALENDAR_JSON)):
        r = _client().post("/content/biz-1/calendar", json={"days": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 3
    assert len(body["posts"]) == 3


def test_schedule_endpoint_returns_200(make_sb):
    sb = make_sb()
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        r = _client().post("/content/biz-1/schedule",
                           json={"posts": [{"day": 1, "platform": "instagram", "caption": "hi"}]})
    assert r.status_code == 200
    assert r.json() == {"scheduled": 1}
