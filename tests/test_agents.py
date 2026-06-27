import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4


@pytest.mark.asyncio
async def test_cmo_agent_returns_response():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    with patch("agents.departments.cmo.agent.get_supabase", return_value=mock_sb), \
         patch("agents.departments.cmo.agent.ChatOpenAI") as MockLLM:
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"status": "ok", "summary": "No active campaigns", "metrics": {}, "recommendations": []}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        MockLLM.return_value = mock_llm
        from agents.departments.cmo.agent import CMOAgent
        agent = CMOAgent(uuid4())
        resp = await agent.run("How are our campaigns performing?")
        assert resp.status == "ok"


@pytest.mark.asyncio
async def test_cfo_agent_returns_response():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = []
    with patch("agents.departments.cfo.agent.get_supabase", return_value=mock_sb), \
         patch("agents.departments.cfo.agent.ChatOpenAI") as MockLLM:
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"status": "ok", "summary": "Revenue tracking", "metrics": {}, "recommendations": []}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        MockLLM.return_value = mock_llm
        from agents.departments.cfo.agent import CFOAgent
        agent = CFOAgent(uuid4())
        resp = await agent.run("What is our revenue this week?")
        assert resp.status == "ok"
