"""Shared tools available to all department agents."""
from typing import Optional


async def raise_disagreement(
    business_id: str,
    disagreeing_agent: str,
    directive_from: str,
    directive_summary: str,
    concern: str,
    alternative_suggestion: Optional[str] = None,
    severity: str = "moderate",
) -> dict:
    """Log a reasoned objection to a directive. Never a veto — just surfaced to owner."""
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    record = sb.table("disagreements").insert({
        "business_id": business_id,
        "disagreeing_agent": disagreeing_agent,
        "directive_from": directive_from,
        "directive_summary": directive_summary,
        "concern": concern,
        "alternative_suggestion": alternative_suggestion,
        "severity": severity,
        "status": "raised",
    }).execute()

    try:
        from backend.events.agent_chat import post_team_message
        await post_team_message(
            business_id=business_id,
            from_agent=disagreeing_agent,
            message=f"⚠️ Concern about directive: {concern}"
                    + (f" Alternative: {alternative_suggestion}" if alternative_suggestion else ""),
            to_agent=directive_from,
            category="disagreement",
            urgency="high" if severity == "significant" else "normal",
        )
    except Exception:
        pass

    if severity == "significant":
        sb.table("recommendations").insert({
            "business_id": business_id,
            "generated_by": disagreeing_agent,
            "category": "disagreement",
            "title": f"{disagreeing_agent.upper()} disagrees with a recent directive",
            "description": f"Directive: {directive_summary}\n\nConcern: {concern}"
                          + (f"\n\nSuggested alternative: {alternative_suggestion}" if alternative_suggestion else ""),
            "priority": "high",
            "status": "pending",
        }).execute()

    return {"disagreement_id": record.data[0]["id"] if record.data else None, "logged": True}
