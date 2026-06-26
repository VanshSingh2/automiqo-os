from fastapi import APIRouter
from uuid import UUID
from backend.memory.supabase_client import get_supabase

router = APIRouter()


@router.get("/approvals/{business_id}")
async def list_approvals(business_id: UUID):
    sb = get_supabase()
    result = sb.table("recommendations") \
        .select("*") \
        .eq("business_id", str(business_id)) \
        .eq("status", "pending") \
        .order("created_at", desc=True) \
        .limit(20) \
        .execute()
    return {"approvals": result.data or []}


@router.post("/approvals/{approval_id}/approve")
async def approve(approval_id: UUID, note: str = ""):
    from datetime import datetime, timezone
    get_supabase().table("recommendations").update({
        "status": "approved",
        "owner_note": note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(approval_id)).execute()
    return {"approved": True}


@router.post("/approvals/{approval_id}/reject")
async def reject(approval_id: UUID, note: str = ""):
    from datetime import datetime, timezone
    get_supabase().table("recommendations").update({
        "status": "rejected",
        "owner_note": note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(approval_id)).execute()
    return {"rejected": True}
