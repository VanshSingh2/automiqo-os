from fastapi import APIRouter
from uuid import UUID
from backend.memory.supabase_client import get_supabase

router = APIRouter()


@router.get("/reports/{business_id}")
async def list_reports(business_id: UUID, limit: int = 10):
    sb = get_supabase()
    result = sb.table("reports").select("*").eq("business_id", str(business_id)).order("generated_at", desc=True).limit(limit).execute()
    return {"reports": result.data or []}


@router.get("/metrics/{business_id}")
async def get_metrics(business_id: UUID):
    from backend.memory.company import get_company_state
    state = await get_company_state(business_id)
    return state


@router.get("/patterns/{business_id}")
async def get_detected_patterns(business_id: UUID):
    from backend.engines.pattern_detector import detect_repeated_failures
    patterns = await detect_repeated_failures(str(business_id))
    return {"patterns": patterns}
