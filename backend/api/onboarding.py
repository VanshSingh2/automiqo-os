from fastapi import APIRouter, HTTPException
from shared.schemas import OnboardRequest
from backend.memory.supabase_client import get_supabase

router = APIRouter()


@router.post("/onboard")
async def onboard_business(req: OnboardRequest):
    sb = get_supabase()
    data = {
        "name": req.name,
        "industry": req.industry,
        "phone": req.phone,
        "email": req.email,
        "address": req.address,
        "timezone": req.timezone,
    }
    result = sb.table("businesses").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create business")
    return result.data[0]
