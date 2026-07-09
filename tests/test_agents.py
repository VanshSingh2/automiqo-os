import pytest
import sys
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

# ---------------------------------------------------------------------------
# Stub all third-party packages that aren't installed in the test environment.
# Must happen before any agent import so collection succeeds.
# ---------------------------------------------------------------------------
def _ensure_stub(name):
    if name not in sys.modules:
        sys.modules[name] = MagicMock()

for _mod in [
    "supabase",
    "langchain_openai",
    "langchain_core",
    "langchain_core.messages",
    "langchain_core.tools",
]:
    _ensure_stub(_mod)

# Realistic constructors so isinstance checks / attribute access work
sys.modules["langchain_core.messages"].HumanMessage = MagicMock(
    side_effect=lambda content: MagicMock(content=content)
)
sys.modules["langchain_core.messages"].SystemMessage = MagicMock(
    side_effect=lambda content: MagicMock(content=content)
)
sys.modules["langchain_openai"].ChatOpenAI = MagicMock
sys.modules["supabase"].create_client = MagicMock()
sys.modules["supabase"].Client = MagicMock

# Now import so patch() can resolve paths
import agents.departments.cmo.agent   # noqa: F401
import agents.departments.cfo.agent   # noqa: F401


def _mock_llm(summary: str):
    """A stand-in LLM whose ainvoke returns a fixed JSON response."""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = f'{{"status": "ok", "summary": "{summary}", "metrics": {{}}, "recommendations": []}}'
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
    return mock_llm


@pytest.mark.asyncio
async def test_cmo_agent_returns_response():
    from agents.base_agent import BaseAgent
    mock_sb = MagicMock()
    # Any query chain resolves to an empty result set.
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_sb.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = []
    mock_llm = _mock_llm("No active campaigns")
    # LLM construction now lives in BaseAgent._build_dept_llm; specialist consults
    # are stubbed so the test makes no network calls.
    with patch("agents.departments.cmo.agent.get_supabase", return_value=mock_sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=mock_llm), \
         patch.object(BaseAgent, "consult_specialists_parallel", AsyncMock(return_value={})), \
         patch.object(BaseAgent, "consult_specialist", AsyncMock(return_value="")):
        from agents.departments.cmo.agent import CMOAgent
        agent = CMOAgent(uuid4())
        resp = await agent.run("How are our campaigns performing?")
        assert resp.status == "ok"


@pytest.mark.asyncio
async def test_cfo_agent_returns_response():
    from agents.base_agent import BaseAgent
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = []
    mock_llm = _mock_llm("Revenue tracking")
    with patch("agents.departments.cfo.agent.get_supabase", return_value=mock_sb), \
         patch.object(BaseAgent, "_build_dept_llm", return_value=mock_llm), \
         patch.object(BaseAgent, "consult_specialists_parallel", AsyncMock(return_value={})), \
         patch.object(BaseAgent, "consult_specialist", AsyncMock(return_value="")):
        from agents.departments.cfo.agent import CFOAgent
        agent = CFOAgent(uuid4())
        resp = await agent.run("What is our revenue this week?")
        assert resp.status == "ok"
