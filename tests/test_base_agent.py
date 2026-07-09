"""Tests for BaseAgent helpers: ResilientLLM retry + response parsing."""
import pytest
from unittest.mock import AsyncMock, patch

from agents.base_agent import ResilientLLM, BaseAgent


# ── ResilientLLM ────────────────────────────────────────────────────────────
async def test_resilient_llm_returns_on_success():
    inner = AsyncMock()
    inner.ainvoke = AsyncMock(return_value="ok")
    llm = ResilientLLM(inner, retries=3)
    assert await llm.ainvoke("x") == "ok"
    inner.ainvoke.assert_awaited_once()


async def test_resilient_llm_retries_then_succeeds():
    inner = AsyncMock()
    inner.ainvoke = AsyncMock(side_effect=[RuntimeError("boom"), "recovered"])
    llm = ResilientLLM(inner, retries=3)
    with patch("agents.base_agent.asyncio.sleep", new=AsyncMock()):
        out = await llm.ainvoke("x")
    assert out == "recovered"
    assert inner.ainvoke.await_count == 2


async def test_resilient_llm_raises_after_exhausting_retries():
    inner = AsyncMock()
    inner.ainvoke = AsyncMock(side_effect=RuntimeError("always fails"))
    llm = ResilientLLM(inner, retries=3)
    with patch("agents.base_agent.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="always fails"):
            await llm.ainvoke("x")
    assert inner.ainvoke.await_count == 3


def test_resilient_llm_delegates_unknown_attrs():
    inner = AsyncMock()
    inner.bind_tools = lambda *a, **k: "bound"
    llm = ResilientLLM(inner)
    assert llm.bind_tools() == "bound"



# ── _parse_response ─────────────────────────────────────────────────────────
def test_parse_response_plain_json():
    r = BaseAgent._parse_response('{"status": "ok", "summary": "hi", "confidence": 0.9}')
    assert r.status == "ok"
    assert r.summary == "hi"
    assert r.confidence == 0.9


def test_parse_response_strips_code_fences():
    raw = "```json\n{\"status\": \"ok\", \"summary\": \"fenced\"}\n```"
    r = BaseAgent._parse_response(raw)
    assert r.summary == "fenced"


def test_parse_response_non_json_becomes_summary():
    r = BaseAgent._parse_response("just some free text, not json")
    assert r.status == "ok"
    assert "free text" in r.summary
    assert r.confidence == 0.5


def test_parse_response_handles_anthropic_list_content():
    blocks = [{"text": "part one "}, {"text": "part two"}]
    r = BaseAgent._parse_response(blocks)
    assert "part one" in r.summary and "part two" in r.summary


def test_parse_response_defaults_confidence():
    r = BaseAgent._parse_response('{"status": "ok", "summary": "s"}')
    assert r.confidence == 0.85
