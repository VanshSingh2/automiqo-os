"""
Public chatbot API — powers a multilingual FAQ chatbot website widget.

This router is intentionally PUBLIC (no auth) so it can be embedded in a
customer-facing website widget. It is still protected against denial-of-wallet
abuse by:
  - the daily AI spend circuit breaker (spend_guard.within_budget), and
  - a per-client sliding-window rate limit (rate_limit dependency, like chat.py).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List

from backend.security.rate_limit import rate_limit

router = APIRouter(tags=["chatbot"])


class AskRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None


@router.post("/chatbot/{business_id}/ask",
             dependencies=[Depends(rate_limit("chatbot", per_minute=30))])
async def ask(business_id: str, req: AskRequest):
    """
    Answer a customer question from the business knowledge base, in their own
    language, and offer to book when relevant. Public endpoint (website widget).
    """
    # Daily spend circuit breaker — degrade gracefully instead of running up cost.
    try:
        from backend.security.spend_guard import within_budget
        allowed, _spent, _cap = await within_budget(str(business_id))
        if not allowed:
            return {
                "reply": "Thanks for reaching out! Our assistant is taking a short "
                         "break right now — please try again a little later, or leave "
                         "us a message and our team will follow up.",
                "language": "en",
                "used_context": False,
                "wants_booking": False,
            }
    except Exception:
        pass

    try:
        from backend.integrations import faq_chatbot
        return await faq_chatbot.answer(business_id, req.message, req.history)
    except Exception:
        return {
            "reply": "Sorry, I'm having trouble answering right now. "
                     "Please try again in a moment or ask to speak with our team.",
            "language": "en",
            "used_context": False,
            "wants_booking": False,
        }
