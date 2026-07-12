"""
Multilingual FAQ Chatbot — a fully-automated customer-facing chatbot that
answers questions ONLY from the business knowledge base (FAQs, policies,
pricing, service descriptions) and offers to book, replying in the customer's
own language.

Designed for a public website widget: it grounds every answer in the business's
own knowledge (pgvector semantic search) + config, stays on-brand, and detects
+ mirrors the customer's language automatically. If it doesn't know, it says so
politely and offers to connect a human.

Style mirrors the rest of the backend: lazy imports, defensive try/except,
async, best-effort DB. Never raises to the caller — any failure degrades to a
friendly fallback reply.
"""
from __future__ import annotations

import json


async def _load_config(business_id: str) -> dict:
    """Best-effort pull of the business profile (name, booking_url, brand_voice)."""
    try:
        from backend.memory.supabase_client import get_supabase
        rows = get_supabase().table("businesses").select("name,config") \
            .eq("id", str(business_id)).limit(1).execute().data or []
    except Exception:
        return {}
    if not rows:
        return {}
    biz = rows[0] or {}
    cfg = biz.get("config") or {}
    return {
        "name": biz.get("name") or cfg.get("name") or "our business",
        "booking_url": cfg.get("booking_url") or "",
        "brand_voice": cfg.get("brand_voice") or "friendly, professional",
    }


async def _search_context(business_id: str, message: str, limit: int = 5) -> list:
    """Semantic-search the knowledge base; fall back to memory_for().recall_facts."""
    try:
        from backend.memory.semantic import semantic_search
        results = await semantic_search(business_id, message, None, limit)
        if results:
            return results
    except Exception:
        pass
    # Fallback path: unified memory recall (Mem0 -> pgvector -> keyword)
    try:
        from backend.memory.memory_service import memory_for
        return await memory_for(business_id).recall_facts(message, limit) or []
    except Exception:
        return []


def _format_context(items: list) -> str:
    """Compact the knowledge items into a prompt-friendly block."""
    parts = []
    for it in items or []:
        if not isinstance(it, dict):
            parts.append(str(it)[:300])
            continue
        title = it.get("title") or it.get("category") or ""
        content = it.get("content") or it.get("memory") or it.get("text") or ""
        line = f"- {title}: {content}".strip(" -:") if title else f"- {content}"
        if line.strip("- "):
            parts.append(line[:500])
    return "\n".join(parts)


def _extract_text(content) -> str:
    """Coerce an LLM response .content (str or list of blocks) into a string."""
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict):
                out.append(block.get("text", "") or block.get("content", ""))
            else:
                out.append(str(block))
        return "".join(out)
    if isinstance(content, str):
        return content
    return str(content)


def _parse_llm(raw: str) -> dict:
    """Parse the LLM reply into {reply, language, wants_booking}. Very forgiving."""
    import re
    text = (raw or "").strip()
    # Strip markdown code fences if present
    m = re.search(r"```[\w]*\s*([\s\S]*?)```", text)
    clean = m.group(1).strip() if m else text
    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            return {
                "reply": str(data.get("reply") or data.get("answer") or "").strip(),
                "language": str(data.get("language") or "en").strip() or "en",
                "wants_booking": bool(data.get("wants_booking", False)),
            }
    except Exception:
        pass
    # Not JSON — treat the whole thing as the reply text.
    return {"reply": text, "language": "en", "wants_booking": False}


async def answer(business_id, message, history=None) -> dict:
    """
    Answer a customer question from the business knowledge base, in their own
    language, and offer to book when relevant.

    Returns:
      {"reply": str, "language": str, "used_context": bool, "wants_booking": bool}
    Any failure degrades to a friendly fallback.
    """
    fallback = {
        "reply": "Sorry, I'm having trouble answering right now. "
                 "Please try again in a moment or ask to speak with our team.",
        "language": "en",
        "used_context": False,
        "wants_booking": False,
    }
    try:
        message = (message or "").strip()
        if not message:
            return {
                "reply": "Hi! How can I help you today?",
                "language": "en", "used_context": False, "wants_booking": False,
            }

        cfg = await _load_config(business_id)
        context_items = await _search_context(business_id, message)
        used_context = bool(context_items)
        context_block = _format_context(context_items) or "(no specific knowledge found)"
        booking_url = cfg.get("booking_url", "")

        history_block = ""
        try:
            if history:
                turns = []
                for h in history[-6:]:
                    if isinstance(h, dict):
                        role = h.get("role", "user")
                        content = h.get("content") or h.get("message") or ""
                        turns.append(f"{role}: {content}")
                    else:
                        turns.append(str(h))
                if turns:
                    history_block = "\n\nConversation so far:\n" + "\n".join(turns)
        except Exception:
            history_block = ""

        system_prompt = (
            f"You are the customer-support assistant for {cfg.get('name', 'our business')}. "
            f"Brand voice: {cfg.get('brand_voice', 'friendly, professional')}.\n"
            "RULES:\n"
            "1. Detect the language of the customer's message and REPLY IN THAT SAME LANGUAGE.\n"
            "2. Answer ONLY using the business knowledge provided below and the booking link. "
            "Do NOT invent facts, prices, hours, or policies that are not present.\n"
            "3. If the customer wants to book, or their question implies booking an "
            "appointment/service, include the booking link"
            + (f" ({booking_url})" if booking_url else " if one is available") + ".\n"
            "4. If the answer is not in the provided knowledge, politely say you don't have "
            "that information and offer to connect them with a human on the team.\n"
            "5. Stay on-brand, concise, and helpful.\n\n"
            f"Booking link: {booking_url or '(none configured)'}\n\n"
            "BUSINESS KNOWLEDGE:\n"
            f"{context_block}\n\n"
            "Respond with a JSON object ONLY, of the form: "
            '{"reply": "<your answer in the customer\'s language>", '
            '"language": "<ISO 639-1 code of the customer\'s language, e.g. en, es, fr>", '
            '"wants_booking": <true|false whether the message is about booking>}'
        )

        try:
            from agents.base_agent import BaseAgent
            from langchain_core.messages import HumanMessage, SystemMessage
            llm = BaseAgent._build_dept_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Customer message:{history_block}\n\n{message}"),
            ]
            response = await llm.ainvoke(messages)
            parsed = _parse_llm(_extract_text(response.content))
        except Exception:
            return {**fallback, "used_context": used_context}

        reply = parsed.get("reply") or ""
        if not reply.strip():
            reply = ("I'm sorry, I don't have that information right now — "
                     "I can connect you with someone on our team who can help.")

        wants_booking = parsed.get("wants_booking", False)
        # Best-effort: ensure the booking link is present when booking is intended.
        if wants_booking and booking_url and booking_url not in reply:
            reply = f"{reply}\n\nYou can book here: {booking_url}"

        return {
            "reply": reply.strip(),
            "language": parsed.get("language", "en") or "en",
            "used_context": used_context,
            "wants_booking": bool(wants_booking),
        }
    except Exception:
        return fallback
