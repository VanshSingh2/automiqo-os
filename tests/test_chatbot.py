"""
Offline tests for the multilingual FAQ chatbot.

Everything heavy is stubbed by conftest (supabase, langchain, openai). Here we
additionally patch:
  - BaseAgent._build_dept_llm -> a fake LLM returning a fixed JSON reply
  - semantic_search           -> fixed knowledge context
  - get_supabase              -> fake business config (name, booking_url, ...)
so no network is ever touched.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _fake_llm(content):
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content=content))
    return llm


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── faq_chatbot.answer() ────────────────────────────────────────────────────
def test_answer_returns_dict_shape(make_sb):
    from backend.integrations import faq_chatbot

    llm = _fake_llm(json.dumps({
        "reply": "Estamos abiertos de 9 a 5. Puedes reservar aqui.",
        "language": "es",
        "wants_booking": True,
    }))
    sb = make_sb({"businesses": [{
        "name": "Glow Spa",
        "config": {"booking_url": "https://book.example.com", "brand_voice": "warm"},
    }]})

    with patch("agents.base_agent.BaseAgent._build_dept_llm", return_value=llm), \
         patch("backend.memory.semantic.semantic_search",
               new=AsyncMock(return_value=[{"title": "Hours", "content": "9am-5pm"}])), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = asyncio.run(faq_chatbot.answer("biz-1", "¿A qué hora abren?"))

    assert isinstance(result, dict)
    assert set(result.keys()) == {"reply", "language", "used_context", "wants_booking"}
    assert result["reply"].strip()
    assert result["language"] == "es"
    assert result["used_context"] is True
    assert result["wants_booking"] is True
    # Booking link surfaced because wants_booking is true
    assert "https://book.example.com" in result["reply"]


def test_answer_falls_back_to_recall_when_semantic_fails(make_sb):
    from backend.integrations import faq_chatbot

    llm = _fake_llm(json.dumps({"reply": "We offer facials.", "language": "en", "wants_booking": False}))
    sb = make_sb({"businesses": [{"name": "Glow Spa", "config": {}}]})

    with patch("agents.base_agent.BaseAgent._build_dept_llm", return_value=llm), \
         patch("backend.memory.semantic.semantic_search",
               new=AsyncMock(side_effect=RuntimeError("no pgvector"))), \
         patch("backend.memory.memory_service.MemoryService.recall_facts",
               new=AsyncMock(return_value=[{"title": "Services", "content": "facials"}])), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = asyncio.run(faq_chatbot.answer("biz-1", "What do you offer?"))

    assert result["used_context"] is True
    assert result["reply"].strip()
    assert result["language"] == "en"


def test_answer_handles_plain_text_reply(make_sb):
    from backend.integrations import faq_chatbot

    llm = _fake_llm("Just a plain text answer, no JSON here.")
    sb = make_sb({"businesses": [{"name": "Glow Spa", "config": {}}]})

    with patch("agents.base_agent.BaseAgent._build_dept_llm", return_value=llm), \
         patch("backend.memory.semantic.semantic_search", new=AsyncMock(return_value=[])), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = asyncio.run(faq_chatbot.answer("biz-1", "Hello"))

    assert result["reply"].strip()
    assert result["used_context"] is False
    assert result["language"] == "en"


def test_answer_llm_error_returns_friendly_fallback(make_sb):
    from backend.integrations import faq_chatbot

    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))
    sb = make_sb({"businesses": [{"name": "Glow Spa", "config": {}}]})

    with patch("agents.base_agent.BaseAgent._build_dept_llm", return_value=llm), \
         patch("backend.memory.semantic.semantic_search", new=AsyncMock(return_value=[])), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        result = asyncio.run(faq_chatbot.answer("biz-1", "Hi"))

    assert isinstance(result, dict)
    assert result["reply"].strip()
    assert result["wants_booking"] is False


# ── /chatbot/{id}/ask endpoint ──────────────────────────────────────────────
def test_ask_endpoint_returns_reply(make_sb):
    from backend.api import chatbot_api

    llm = _fake_llm(json.dumps({"reply": "Bonjour! Nous sommes ouverts.", "language": "fr", "wants_booking": False}))
    sb = make_sb({"businesses": [{"name": "Glow Spa", "config": {}}]})

    with patch("agents.base_agent.BaseAgent._build_dept_llm", return_value=llm), \
         patch("backend.memory.semantic.semantic_search",
               new=AsyncMock(return_value=[{"title": "Hours", "content": "9-5"}])), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        r = _client(chatbot_api.router).post(
            "/chatbot/biz-1/ask", json={"message": "Bonjour, êtes-vous ouvert?"})

    assert r.status_code == 200
    body = r.json()
    assert body["reply"].strip()
    assert body["language"] == "fr"
    assert set(body.keys()) == {"reply", "language", "used_context", "wants_booking"}


def test_ask_endpoint_budget_exceeded_returns_polite_reply(make_sb):
    from backend.api import chatbot_api

    sb = make_sb({"businesses": [{"name": "Glow Spa", "config": {}}]})
    with patch("backend.security.spend_guard.within_budget",
               new=AsyncMock(return_value=(False, 100.0, 50.0))), \
         patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        r = _client(chatbot_api.router).post(
            "/chatbot/biz-1/ask", json={"message": "hi"})

    assert r.status_code == 200
    body = r.json()
    assert body["reply"].strip()
    assert body["used_context"] is False
