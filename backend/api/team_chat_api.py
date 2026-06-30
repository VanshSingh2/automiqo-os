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


_AGENT_PATHS = {
    "ceo": "agents.executive.ceo.agent.CEOAgent",
    "coo": "agents.departments.coo.agent.COOAgent",
    "cmo": "agents.departments.cmo.agent.CMOAgent",
    "cro": "agents.departments.cro.agent.CROAgent",
    "cfo": "agents.departments.cfo.agent.CFOAgent",
    "cto": "agents.departments.cto.agent.CTOAgent",
    "csd": "agents.departments.customer_success.agent.CustomerSuccessAgent",
    "learning": "agents.departments.learning.agent.LearningDirectorAgent",
}


class AskMember(BaseModel):
    agent_key: str
    message: str


@router.post("/team/{business_id}/ask")
async def ask_member(business_id: str, body: AskMember):
    """
    Owner chats 1:1 with a team member. Managers route to their department head
    (with manager context). Stores both sides as a DM thread and returns the reply.
    """
    from uuid import UUID
    import importlib
    from backend.engines.business_blueprint import member_display, MANAGER_DESCRIPTIONS, DEPARTMENTS
    from backend.events.agent_chat import post_team_message

    agent_key = body.agent_key
    name = member_display(agent_key)
    dept = "ceo" if agent_key == "ceo" else agent_key.split(".", 1)[0]
    path = _AGENT_PATHS.get(dept)
    if not path:
        return {"reply": f"Unknown team member '{agent_key}'.", "member": name}

    # Build the question, adding manager context if this is a manager.
    question = body.message
    if "." in agent_key:
        manager = agent_key.split(".", 1)[1]
        mlabel = DEPARTMENTS.get(dept, {}).get("managers", {}).get(manager, name)
        mdesc = MANAGER_DESCRIPTIONS.get(agent_key, "")
        question = (f"[You are the {mlabel} ({mdesc}). The owner is messaging you directly.] "
                    f"{body.message}")

    # Record the owner's message in the DM thread.
    await post_team_message(business_id, "owner", body.message, to_agent=name, channel="dm")

    # Run the agent.
    try:
        module_path, class_name = path.rsplit(".", 1)
        cls = getattr(importlib.import_module(module_path), class_name)
        agent = cls(UUID(business_id))
        resp = await agent.run(question, context={"_dm_from": "owner", "_member": agent_key})
        reply = getattr(resp, "summary", None) or "Done."
    except Exception as e:
        reply = f"(Couldn't reach this member right now: {e})"

    # Record the member's reply.
    await post_team_message(business_id, name, reply, to_agent="Owner", channel="dm")
    return {"member": name, "reply": reply}
