"""
Daily AI spend circuit breaker (review finding B2).

Before an on-demand agent run, check how much this business has spent on AI today
against a configurable cap. If exceeded, the caller degrades gracefully (queues /
declines) instead of running up an unbounded bill.

Cap is set via DAILY_AI_SPEND_CAP_USD (0 or unset = unlimited / disabled).
Reads the existing `ai_costs` table (business_id, date, cost_usd).
"""
from __future__ import annotations
import os
from datetime import datetime, timezone


def _cap() -> float:
    try:
        return float(os.getenv("DAILY_AI_SPEND_CAP_USD", "0") or 0)
    except ValueError:
        return 0.0


async def spent_today(business_id: str) -> float:
    """Sum of cost_usd for this business for today (UTC). 0 on any error."""
    try:
        from backend.memory.supabase_client import get_supabase
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = get_supabase().table("ai_costs").select("cost_usd") \
            .eq("business_id", str(business_id)).eq("date", today).execute().data or []
        return round(sum(float(r.get("cost_usd") or 0) for r in rows), 4)
    except Exception:
        return 0.0


async def within_budget(business_id: str) -> tuple[bool, float, float]:
    """
    Returns (allowed, spent, cap).
    allowed is True when there's no cap or spend is under it.
    """
    cap = _cap()
    if cap <= 0:
        return True, 0.0, 0.0
    spent = await spent_today(business_id)
    return (spent < cap), spent, cap
