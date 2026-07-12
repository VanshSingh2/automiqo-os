"""UGC Ad Studio tests (offline).

Covers:
  * generate_ad_concepts parses fake-LLM JSON into a concepts list;
  * generate_video returns script_only when VIDEO_API_KEY is unset;
  * the ugc router mounts on a throwaway app and its routes return 200.

The LLM is faked by patching BaseAgent._build_dept_llm (heavy SDKs are already
stubbed by conftest), so nothing here touches the network.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.integrations import ugc_ad_studio


def _fake_llm(concepts):
    """A fake LLM whose ainvoke returns strict-JSON concepts."""
    llm = MagicMock()
    payload = json.dumps({"concepts": concepts})
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content=payload))
    return llm


_SAMPLE = [
    {
        "hook": "POV: you finally found the fix",
        "angle": "problem/solution",
        "script": "I struggled for months until...",
        "cta": "Tap the link to try it",
        "visual_direction": "handheld selfie, quick cuts, on-screen captions",
    },
    {
        "hook": "3 reasons this went viral",
        "angle": "listicle",
        "script": "Reason one, reason two...",
        "cta": "Comment MORE for the guide",
        "visual_direction": "text overlay countdown, b-roll",
    },
]


@pytest.mark.asyncio
async def test_generate_ad_concepts_returns_concepts():
    from agents.base_agent import BaseAgent

    with patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm(_SAMPLE)):
        result = await ugc_ad_studio.generate_ad_concepts(
            "biz-1", "Vitamin C serum", count=2, platform="tiktok"
        )

    assert result["platform"] == "tiktok"
    assert isinstance(result["concepts"], list)
    assert len(result["concepts"]) == 2
    first = result["concepts"][0]
    assert set(first.keys()) == {"hook", "angle", "script", "cta", "visual_direction"}
    assert first["hook"]


@pytest.mark.asyncio
async def test_generate_ad_concepts_respects_count_and_platform():
    from agents.base_agent import BaseAgent

    with patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm(_SAMPLE)):
        result = await ugc_ad_studio.generate_ad_concepts(
            "biz-1", "Fitness app", count=1, platform="reels"
        )
    assert result["platform"] == "reels"
    assert len(result["concepts"]) == 1


@pytest.mark.asyncio
async def test_generate_ad_concepts_defensive_on_error():
    from agents.base_agent import BaseAgent

    bad = MagicMock()
    bad.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch.object(BaseAgent, "_build_dept_llm", return_value=bad):
        result = await ugc_ad_studio.generate_ad_concepts("biz-1", "Anything")
    assert result == {"platform": "tiktok", "concepts": []}


@pytest.mark.asyncio
async def test_generate_video_script_only_without_key(monkeypatch):
    monkeypatch.delenv("VIDEO_API_KEY", raising=False)
    concept = _SAMPLE[0]
    result = await ugc_ad_studio.generate_video(concept, business_id="biz-1")
    assert result["status"] == "script_only"
    assert "VIDEO_API_KEY" in result["note"]
    assert result["concept"] == concept


def test_ugc_router_concepts_endpoint_200():
    from agents.base_agent import BaseAgent
    from backend.api.ugc_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with patch.object(BaseAgent, "_build_dept_llm", return_value=_fake_llm(_SAMPLE)):
        resp = client.post(
            "/ugc/biz-1/concepts",
            json={"product": "Cold brew kit", "count": 2, "platform": "tiktok"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["platform"] == "tiktok"
    assert len(body["concepts"]) == 2


def test_ugc_router_video_endpoint_200(monkeypatch):
    from backend.api.ugc_api import router

    monkeypatch.delenv("VIDEO_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/ugc/biz-1/video", json={"concept": _SAMPLE[0]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "script_only"
