"""
Team Chat API — powers the owner-facing group chat + backstage activity feed.

  GET  /team-chat/{business_id}      → the group chat between CEO/depts/managers
  POST /team-chat/{business_id}      → owner posts a message into the group chat
  GET  /backstage/{business_id}      → backend activity translated to plain English
"""
from fastapi import APIRouter
from pydantic import BaseModel
from backend.memory.supabase_client import get_supabase

router = APIRouter(tags=["team-chat"])


@router.get("/team-chat/{business_id}")
async def get_team_chat(business_id: str, limit: int = 60):
    """Return recent team-chat messages, oldest first (chat order)."""
    try:
        sb = get_supabase()
        rows = sb.table("agent_messages").select(
            "id,from_agent,from_role,to_agent,message,category,urgency,created_at"
        ).eq("business_id", business_id).eq("channel", "team") \
         .order("created_at", desc=True).limit(min(limit, 200)).execute().data or []
        rows.reverse()  # oldest -> newest for display
        return {"messages": rows}
    except Exception as e:
        return {"messages": [], "error": str(e)}


class OwnerMessage(BaseModel):
    message: str
    to_agent: str = "team"


@router.post("/team-chat/{business_id}")
async def post_owner_message(business_id: str, body: OwnerMessage):
    """Owner drops a message into the team chat (visible to all agents)."""
    from backend.events.agent_chat import post_team_message
    mid = await post_team_message(
        business_id, from_agent="owner", message=body.message,
        to_agent=body.to_agent, category="update",
    )
    return {"posted": bool(mid), "id": mid}


@router.get("/backstage/{business_id}")
async def get_backstage(business_id: str, limit: int = 80):
    """
    Backend activity feed in plain English — derived from the events table,
    so it reflects everything happening under the hood with no extra storage.
    """
    from backend.events.agent_chat import translate_event
    try:
        sb = get_supabase()
        rows = sb.table("events").select("id,event_type,payload,created_at") \
            .eq("business_id", business_id) \
            .order("created_at", desc=True).limit(min(limit, 200)).execute().data or []
        feed = [translate_event(r) for r in rows]
        return {"activity": feed}
    except Exception as e:
        return {"activity": [], "error": str(e)}
