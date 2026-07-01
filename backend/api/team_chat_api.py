"""
Team Chat API — powers the owner-facing group chat + backstage activity feed.

  GET  /team-chat/{business_id}      → the group chat between CEO/depts/managers
  POST /team-chat/{business_id}      → owner posts a message into the group chat
  GET  /backstage/{business_id}      → backend activity translated to plain English
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from backend.memory.supabase_client import get_supabase
from backend.security.rate_limit import rate_limit
from backend.security.spend_guard import within_budget

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


# ── Team roster + 1:1 chat with a member ────────────────────────────────────
def _load_config(business_id: str) -> dict:
    try:
        sb = get_supabase()
        biz = sb.table("businesses").select("config,industry").eq("id", business_id).limit(1).execute().data
        if not biz:
            return {}
        cfg = biz[0].get("config") or {}
        cfg.setdefault("industry", biz[0].get("industry"))
        return cfg
    except Exception:
        return {}


@router.get("/team/{business_id}/members")
async def get_team_members(business_id: str):
    """Full roster: who's on the team, what they do, and whether they're on."""
    from backend.engines.business_blueprint import team_roster
    return team_roster(_load_config(business_id))


@router.get("/team/{business_id}/dm/{agent_key}")
async def get_dm(business_id: str, agent_key: str, limit: int = 50):
    """1:1 message history between the owner and a specific team member."""
    from backend.engines.business_blueprint import member_display
    name = member_display(agent_key)
    try:
        sb = get_supabase()
        rows = sb.table("agent_messages").select(
            "id,from_agent,from_role,to_agent,message,created_at"
        ).eq("business_id", business_id).eq("channel", "dm") \
         .order("created_at", desc=True).limit(min(limit, 200)).execute().data or []
        # keep only this thread (owner <-> member)
        thread = [m for m in rows if m.get("from_agent") == name or m.get("to_agent") == name]
        thread.reverse()
        return {"member": name, "messages": thread}
    except Exception as e:
        return {"member": name, "messages": [], "error": str(e)}


class AskMember(BaseModel):
    agent_key: str
    message: str


@router.post("/team/{business_id}/ask", dependencies=[Depends(rate_limit("ask", per_minute=15))])
async def ask_member(business_id: str, body: AskMember):
    """
    Owner chats 1:1 with a team member. Each member answers in their own voice
    (PersonaChatAgent) with the live business profile + their recalled memory.
    Stores both sides as a DM thread and returns the reply.
    """
    from uuid import UUID
    from backend.engines.business_blueprint import member_display
    from backend.events.agent_chat import post_team_message

    agent_key = body.agent_key
    name = member_display(agent_key)

    # Daily spend circuit breaker (review finding B2).
    allowed, spent, cap = await within_budget(business_id)
    if not allowed:
        return {"member": name,
                "reply": (f"(The team's paused on-demand AI for today — daily budget "
                          f"of ${cap:.2f} reached at ${spent:.2f}. Raise DAILY_AI_SPEND_CAP_USD "
                          f"or try tomorrow.)")}

    # Record the owner's message in the DM thread.
    await post_team_message(business_id, "owner", body.message, to_agent=name, channel="dm")

    # Answer in character.
    try:
        from agents.persona_chat import PersonaChatAgent
        agent = PersonaChatAgent(UUID(business_id), agent_key)
        resp = await agent.run(body.message)
        reply = getattr(resp, "summary", None) or "Done."
    except Exception as e:
        reply = f"(Couldn't reach this member right now: {e})"

    # Record the member's reply.
    await post_team_message(business_id, name, reply, to_agent="Owner", channel="dm")
    return {"member": name, "reply": reply}
