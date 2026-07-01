"""
Work Memory — the thin layer that lets agents remember what they did and
recall it later, so the team builds shared context instead of re-reading the
database cold every day.

It rides on the existing unified MemoryService (Mem0 -> pgvector -> keyword),
so there's no new infrastructure. Two simple calls:

    recall_block(business_id, agent, query)  -> a short text block to drop in a prompt
    remember_summary(business_id, agent, summary) -> store today's work

All calls are best-effort and never raise — memory must never break a loop.
"""
from __future__ import annotations
from datetime import datetime, timezone


def _line_from(item) -> str:
    """Coerce a recalled memory item (dict or str) into one short line."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for k in ("memory", "content", "what_happened", "text", "value", "title"):
            v = item.get(k)
            if v:
                return str(v).strip()
    return str(item).strip()


async def recall_block(business_id: str, agent: str, query: str, limit: int = 4) -> str:
    """
    Return a compact 'what you remember' block for a prompt, e.g.:

        \n\nWhat you remember from recent days:
        - Yesterday no-show rate was 22%, asked CMO to prep re-engagement.
        - Inventory on serum was low; reorder queued for approval.

    Empty string if nothing is remembered yet.
    """
    try:
        from backend.memory.memory_service import memory_for
        facts = await memory_for(str(business_id)).recall_facts(query, limit=limit)
    except Exception:
        facts = []
    lines = []
    for f in (facts or [])[:limit]:
        line = _line_from(f)
        if line:
            # Recalled memory may contain externally-derived content — treat as untrusted.
            try:
                from backend.security.sanitize import sanitize_external
                line = sanitize_external(line, max_len=200)
            except Exception:
                line = line[:200]
            lines.append(f"- {line}")
    if not lines:
        return ""
    return "\n\nWhat you remember from recent days:\n" + "\n".join(lines)


async def remember_summary(business_id: str, agent: str, summary: str,
                           category: str = "daily_work") -> None:
    """Store a concise summary of what this agent did/observed today."""
    if not summary or not summary.strip():
        return
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"{agent} — {category} {date}"
    try:
        from backend.memory.memory_service import memory_for
        mem = memory_for(str(business_id))
        # Durable fact (Mem0/pgvector) so it's recallable by any teammate.
        await mem.remember_fact(summary, title=title, category=category, agent=agent)
        # Episodic note (reflections) for the learning loop's timeline.
        try:
            await mem.remember_event(what_happened=summary, agent=agent)
        except Exception:
            pass
    except Exception:
        pass
