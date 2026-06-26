from uuid import UUID
from typing import Optional
from backend.memory.supabase_client import get_supabase


async def save_reflection(
    business_id: UUID,
    task_id: UUID,
    agent_name: str,
    what_happened: str,
    why: str,
    confidence: float,
    lesson: str,
    mistake: bool = False,
    recommendation: Optional[str] = None,
) -> dict:
    sb = get_supabase()
    data = {
        "business_id": str(business_id),
        "task_id": str(task_id),
        "agent_name": agent_name,
        "what_happened": what_happened,
        "why": why,
        "confidence": confidence,
        "mistake": mistake,
        "lesson": lesson,
        "recommendation": recommendation,
    }
    result = sb.table("reflections").insert(data).execute()
    return result.data[0] if result.data else {}
