"""Tests for the memory layer: Mem0 backend + unified MemoryService fallback chain."""
from unittest.mock import patch, MagicMock

from backend.memory import mem0_backend
from backend.memory.memory_service import MemoryService, memory_for


# ── Mem0 availability / graceful degradation ────────────────────────────────
def test_mem0_unavailable_without_db_url(monkeypatch):
    monkeypatch.delenv("MEM0_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert mem0_backend.is_available() is False


def test_mem0_available_when_db_url_set(monkeypatch):
    # mem0 is importable (stubbed in conftest); with a DB URL it's "available".
    monkeypatch.setenv("MEM0_DB_URL", "postgresql://u:p@h:5432/db")
    assert mem0_backend.is_available() is True


def test_mem0_add_returns_false_when_unavailable(monkeypatch):
    monkeypatch.delenv("MEM0_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    # False signals the caller to use the pgvector fallback
    assert mem0_backend.add("biz", "some fact") is False


def test_mem0_search_returns_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("MEM0_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    # None signals "fall back to pgvector"
    assert mem0_backend.search("biz", "query") is None


def test_mem0_search_normalizes_dict_result(monkeypatch):
    monkeypatch.setenv("MEM0_DB_URL", "postgresql://u:p@h:5432/db")
    client = MagicMock()
    client.search.return_value = {"results": [{"memory": "x", "score": 0.9}]}
    monkeypatch.setattr(mem0_backend, "_get_client", lambda: client)
    out = mem0_backend.search("biz", "query")
    assert out == [{"memory": "x", "score": 0.9}]



# ── MemoryService recall fallback chain: Mem0 -> pgvector -> keyword ─────────
async def test_recall_facts_uses_mem0_when_available():
    hits = [{"memory": "VIP prefers texts", "metadata": {"title": "pref", "category": "cust"}, "score": 0.8}]
    with patch("backend.memory.mem0_backend.search", return_value=hits):
        out = await MemoryService("biz-1").recall_facts("preferences")
    assert out[0]["content"] == "VIP prefers texts"
    assert out[0]["title"] == "pref"


async def test_recall_facts_falls_back_to_keyword(make_sb):
    rows = [
        {"title": "Refund policy", "content": "we offer refunds within 30 days", "category": "policy"},
        {"title": "Hours", "content": "open nine to five", "category": "faq"},
    ]
    sb = make_sb({"knowledge": rows})
    with patch("backend.memory.mem0_backend.search", return_value=None), \
         patch("backend.memory.semantic.semantic_search", return_value=[]), \
         patch("backend.memory.memory_service.get_supabase", return_value=sb):
        out = await MemoryService("biz-1").recall_facts("refunds refund", limit=1)
    # keyword scorer should rank the refund row first
    assert out[0]["title"] == "Refund policy"


async def test_recall_facts_uses_pgvector_when_mem0_none(make_sb):
    pg_results = [{"title": "svc", "content": "botox $300", "category": "service"}]
    with patch("backend.memory.mem0_backend.search", return_value=None), \
         patch("backend.memory.semantic.semantic_search", return_value=pg_results):
        out = await MemoryService("biz-1").recall_facts("botox")
    assert out == pg_results


async def test_remember_fact_returns_early_when_mem0_handles_it():
    with patch("backend.memory.mem0_backend.add", return_value=True) as m_add, \
         patch("backend.memory.semantic.embed_and_store") as m_embed:
        await MemoryService("biz-1").remember_fact("a durable fact")
    m_add.assert_called_once()
    m_embed.assert_not_called()  # never reached the fallback


async def test_remember_fact_falls_back_to_pgvector(make_sb):
    with patch("backend.memory.mem0_backend.add", return_value=False), \
         patch("backend.memory.semantic.embed_and_store") as m_embed:
        await MemoryService("biz-1").remember_fact("fact", title="t", category="c")
    m_embed.assert_awaited_once()


async def test_recall_kv_returns_value(make_sb):
    sb = make_sb({"agent_memory": [{"value": "stored-value"}]})
    with patch("backend.memory.memory_service.get_supabase", return_value=sb):
        val = await MemoryService("biz-1").recall_kv("some_key")
    assert val == "stored-value"


async def test_build_context_assembles_facts_and_events():
    svc = MemoryService("biz-1")
    with patch.object(svc, "recall_facts", return_value=[{"title": "F", "content": "fact body"}]), \
         patch.object(svc, "recall_events", return_value=[{"what_happened": "did X", "lesson": "learned Y"}]):
        ctx = await svc.build_context("q")
    assert "Known facts" in ctx and "Past lessons" in ctx


def test_memory_for_returns_service():
    assert isinstance(memory_for("biz-1"), MemoryService)
