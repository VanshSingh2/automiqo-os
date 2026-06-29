"""
Growth API — outbound calling, nurture sequences, referrals.
"""
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["growth"])


# ── VAPI Outbound Calls ───────────────────────────────────────────────────────

class OutboundCallRequest(BaseModel):
    business_id: str
    customer_phone: str
    purpose: str = "missed_call_recovery"   # missed_call_recovery | reactivation | reminder | follow_up | lead_qualification
    customer_name: str = ""
    context: dict = {}


@router.post("/calls/outbound")
async def make_outbound_call(req: OutboundCallRequest):
    """Initiate an outbound AI phone call via VAPI."""
    from backend.integrations.vapi_caller import make_outbound_call
    return await make_outbound_call(
        customer_phone=req.customer_phone,
        business_id=req.business_id,
        purpose=req.purpose,
        context={"customer_name": req.customer_name, **req.context},
    )


@router.get("/calls/{call_id}/status")
async def get_call_status(call_id: str):
    """Get VAPI call status and transcript."""
    from backend.integrations.vapi_caller import get_call_status
    return await get_call_status(call_id)


@router.get("/calls/{business_id}/history")
async def call_history(business_id: str, limit: int = 20, direction: str = None):
    """Get call history for a business."""
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    q = sb.table("calls").select("*").eq("business_id", business_id).order("called_at", desc=True).limit(limit)
    if direction:
        q = q.eq("direction", direction)
    return q.execute().data or []


# ── Nurture Sequences ─────────────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    business_id: str
    contact_id: str
    contact_type: str = "lead"
    phone: str = ""
    email: str = ""
    sequence_name: str                      # cold_lead | warm_lead | post_visit | no_show | win_back
    context: dict = {}


@router.post("/nurture/enroll")
async def enroll_sequence(req: EnrollRequest):
    """Enroll a lead or customer in a nurture sequence."""
    from backend.integrations.nurture_sequences import enroll_in_sequence
    return await enroll_in_sequence(
        business_id=req.business_id,
        contact_id=req.contact_id,
        contact_type=req.contact_type,
        phone=req.phone,
        email=req.email,
        sequence_name=req.sequence_name,
        context=req.context,
    )


@router.post("/nurture/run-due")
async def run_due_sequences(business_id: str):
    """Process all due sequence steps for a business. Called by heartbeat."""
    from backend.integrations.nurture_sequences import run_due_sequences
    return await run_due_sequences(business_id)


@router.get("/nurture/{business_id}/stats")
async def nurture_stats(business_id: str):
    """Get nurture sequence stats."""
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    try:
        stats = sb.table("sequence_stats").select("*").eq("business_id", business_id).execute().data or []
    except Exception:
        enrollments = sb.table("sequence_enrollments").select("sequence_name,status")\
            .eq("business_id", business_id).execute().data or []
        from collections import defaultdict
        stats_dict = defaultdict(lambda: {"active": 0, "completed": 0, "paused": 0, "total": 0})
        for e in enrollments:
            stats_dict[e["sequence_name"]]["total"] += 1
            stats_dict[e["sequence_name"]][e.get("status", "active")] = \
                stats_dict[e["sequence_name"]].get(e.get("status", "active"), 0) + 1
        stats = [{"sequence_name": k, **v} for k, v in stats_dict.items()]
    return stats


@router.delete("/nurture/{enrollment_id}")
async def pause_enrollment(enrollment_id: str, reason: str = "manual"):
    """Pause a nurture sequence enrollment."""
    from backend.integrations.nurture_sequences import pause_sequence
    await pause_sequence(enrollment_id, reason)
    return {"paused": True, "enrollment_id": enrollment_id}


# ── Referrals ─────────────────────────────────────────────────────────────────

class CreateReferralRequest(BaseModel):
    business_id: str
    customer_id: str
    customer_name: str = ""
    reward_amount: float = 25.0


class RedeemReferralRequest(BaseModel):
    business_id: str
    referral_code: str
    referred_customer_id: str


@router.post("/referrals/create")
async def create_referral(req: CreateReferralRequest):
    """Generate a referral code for a customer."""
    from backend.integrations.referral_manager import create_referral_code
    return await create_referral_code(
        business_id=req.business_id,
        customer_id=req.customer_id,
        customer_name=req.customer_name,
        reward_amount=req.reward_amount,
    )


@router.post("/referrals/redeem")
async def redeem_referral(req: RedeemReferralRequest):
    """Redeem a referral code when a referred customer books."""
    from backend.integrations.referral_manager import redeem_referral
    return await redeem_referral(
        business_id=req.business_id,
        referral_code=req.referral_code,
        referred_customer_id=req.referred_customer_id,
    )


@router.get("/referrals/{business_id}/stats")
async def referral_stats(business_id: str):
    """Get referral program stats."""
    from backend.integrations.referral_manager import get_referral_stats
    return await get_referral_stats(business_id)


# ── Availability ──────────────────────────────────────────────────────────────

@router.get("/availability/check")
async def check_availability(business_id: str, date: Optional[str] = None, service: Optional[str] = None):
    """Check Cal.com availability and return next available slots."""
    from backend.conversations.manager import check_availability_calcom
    return await check_availability_calcom(date=date, service=service)
