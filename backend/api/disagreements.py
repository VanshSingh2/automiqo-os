from fastapi import APIRouter
from uuid import UUID
from pydantic import BaseModel
from backend.memory.supabase_client import get_supabase

router = APIRouter()


@router.get("/disagreements/{business_id}")
async def list_disagreements(business_id: UUID, status: str = "raised"):
    sb = get_supabase()
    rows = sb.table("disagreements").select("*")\
        .eq("business_id", str(business_id))\
        .eq("status", status)\
        .order("created_at", desc=True).execute().data or []
    return {"disagreements": rows, "count": len(rows)}


class ResolveDisagreement(BaseModel):
    status: str
    owner_response: str = ""


@router.patch("/disagreements/{disagreement_id}")
async def resolve_disagreement(disagreement_id: str, body: ResolveDisagreement):
    from datetime import datetime, timezone
    sb = get_supabase()
    sb.table("disagreements").update({
        "status": body.status,
        "owner_response": body.owner_response,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", disagreement_id).execute()
    return {"updated": True}
