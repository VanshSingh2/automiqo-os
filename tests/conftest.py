"""
Shared test fixtures + offline stubs.

Every heavy third-party dependency (supabase, langchain, openai, mem0, redis,
httpx, langgraph) is stubbed in sys.modules BEFORE any backend/agent import, so
the full suite runs deterministically with no network and no installed SDKs.

Fixtures:
  make_sb   -> factory building a configurable fake Supabase client
  fake_llm  -> factory building a fake LLM whose ainvoke returns fixed JSON
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── import path ───────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── env defaults (modules read some of these at import time) ────────────────
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long-xx")
os.environ.setdefault("RATE_LIMIT_ENABLED", "true")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "30")


# ── stub heavy third-party modules ──────────────────────────────────────────
def _stub(name):
    if name not in sys.modules:
        sys.modules[name] = MagicMock()
    return sys.modules[name]


# NOTE: httpx is intentionally NOT stubbed — FastAPI's TestClient needs the real
# one. Tests that exercise httpx (dispatcher retry) patch the client directly.
for _m in [
    "supabase", "langchain_openai", "langchain_anthropic",
    "langchain_core", "langchain_core.messages", "langchain_core.tools",
    "openai", "mem0", "redis", "redis.asyncio",
    "langgraph", "langgraph.graph", "langgraph.prebuilt", "langgraph.checkpoint",
]:
    _stub(_m)

_msg = sys.modules["langchain_core.messages"]
_msg.HumanMessage = MagicMock(side_effect=lambda content="", **k: SimpleNamespace(content=content))
_msg.SystemMessage = MagicMock(side_effect=lambda content="", **k: SimpleNamespace(content=content))
_msg.AIMessage = MagicMock(side_effect=lambda content="", **k: SimpleNamespace(content=content))
sys.modules["langchain_openai"].ChatOpenAI = MagicMock
sys.modules["langchain_anthropic"].ChatAnthropic = MagicMock
sys.modules["openai"].AsyncOpenAI = MagicMock
sys.modules["openai"].OpenAI = MagicMock
sys.modules["supabase"].create_client = MagicMock()
sys.modules["supabase"].Client = MagicMock


# Make langchain's @tool an identity decorator so tool-decorated functions
# (e.g. the CEO tools) stay real, callable coroutines in tests.
def _identity_tool(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]
    return lambda f: f


sys.modules["langchain_core.tools"].tool = _identity_tool



# ── Fake Supabase client ────────────────────────────────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable query builder; every filter returns self, execute() returns data."""
    _BUILDERS = ("select", "eq", "neq", "gte", "gt", "lte", "lt", "in_", "is_",
                 "like", "ilike", "contains", "order", "limit", "range", "single")

    def __init__(self, rows, insert_id):
        self._rows = rows
        self._insert_id = insert_id
        self._pending = None
        self.inserted, self.updated, self.upserted, self.deleted = [], [], [], False

    def __getattr__(self, name):
        if name in self._BUILDERS:
            return lambda *a, **k: self
        raise AttributeError(name)

    def insert(self, payload, *a, **k):
        self.inserted.append(payload)
        self._pending = "insert"
        return self

    def update(self, payload, *a, **k):
        self.updated.append(payload)
        self._pending = "update"
        return self

    def upsert(self, payload, *a, **k):
        self.upserted.append(payload)
        self._pending = "upsert"
        return self

    def delete(self, *a, **k):
        self.deleted = True
        self._pending = "delete"
        return self

    def execute(self):
        if self._pending == "insert":
            self._pending = None
            return _Result([{"id": self._insert_id}])
        return _Result(list(self._rows))


class FakeSupabase:
    def __init__(self, table_data=None, insert_id="fake-id-123"):
        self.table_data = table_data or {}
        self.insert_id = insert_id
        self.queries = {}

    def table(self, name):
        q = _Query(self.table_data.get(name, []), self.insert_id)
        self.queries[name] = q
        return q

    def rpc(self, name, params=None):
        return _Query(self.table_data.get(f"rpc:{name}", []), self.insert_id)



# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def make_sb():
    """Factory: make_sb({'ai_costs': [{'cost_usd': 1.0}]}) -> FakeSupabase."""
    def _factory(table_data=None, insert_id="fake-id-123"):
        return FakeSupabase(table_data=table_data, insert_id=insert_id)
    return _factory


@pytest.fixture
def fake_llm():
    """Factory: fake_llm('{"status":"ok",...}') -> object with async ainvoke."""
    def _factory(content='{"status": "ok", "summary": "ok", "metrics": {}, "recommendations": []}'):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content=content))
        return llm
    return _factory


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Clear the in-process rate-limit window between tests."""
    try:
        from backend.security.rate_limit import _HITS
        _HITS.clear()
    except Exception:
        pass
    yield
    try:
        from backend.security.rate_limit import _HITS
        _HITS.clear()
    except Exception:
        pass
