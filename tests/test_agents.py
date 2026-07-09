"""Tests for department agents: they parse LLM JSON into an AgentResponse.

LLM construction lives in BaseAgent._build_dept_llm; specialist consults and
Supabase are stubbed so these run offline with no network.
"""
from unittest.mock import AsyncMock, patch

from agents.base_agent import BaseAgent


def _agent_ctx(make_sb, llm_json):
    """Common patches: fake LLM + fake Supabase + stubbed specialist consults."""
    from tests.conftest import FakeSupabase  # noqa
    sb = make_sb()
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content=llm_json))
    return sb, llm


async def test_cmo_agent_returns_response(make_sb):
    sb, llm = _agent_ctx(make_sb, '{"status": "ok", "summary": "No active campaigns", "metrics": {}, "recommendations": []}')
    with patch("agents.departments.cmo.agent.get_supabase", return_value=sb), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=llm), \
         patch.object(BaseAgent, "consult_specialists_parallel", AsyncMock(return_value={})), \
         patch.object(BaseAgent, "consult_specialist", AsyncMock(return_value="")):
        from agents.departments.cmo.agent import CMOAgent
        from uuid import uuid4
        resp = await CMOAgent(uuid4()).run("How are our campaigns performing?")
    assert resp.status == "ok"


async def test_cfo_agent_returns_response(make_sb):
    sb, llm = _agent_ctx(make_sb, '{"status": "ok", "summary": "Revenue tracking", "metrics": {}, "recommendations": []}')
    with patch("agents.departments.cfo.agent.get_supabase", return_value=sb), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=llm), \
         patch.object(BaseAgent, "consult_specialists_parallel", AsyncMock(return_value={})), \
         patch.object(BaseAgent, "consult_specialist", AsyncMock(return_value="")):
        from agents.departments.cfo.agent import CFOAgent
        from uuid import uuid4
        resp = await CFOAgent(uuid4()).run("What is our revenue this week?")
    assert resp.status == "ok"
