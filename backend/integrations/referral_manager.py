"""
Referral Manager — generates unique referral codes, tracks conversions, credits referrers.
"""
import os
import hashlib
import random
import string
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


def _generate_code(customer_name: str, customer_id: str) -> str:
    """Generate a short unique referral code like JANE2024."""
    name_part = (customer_name or "USER")[:4].upper().replace(" ", "")
    rand_part = "".join(random.choices(string.digits, k=4))
    return f"{name_part}{rand_part}"


async def create_referral_code(business_id: str, customer_id: str,
                                 customer_name: str = "", reward_amount: float = 25.0) -> dict:
    """Create or retrieve a referral code for a customer."""
    sb = get_supabase()
    existing = sb.table("referrals").select("referral_code,id")\
        .eq("business_id", business_id).eq("referrer_id", customer_id)\
        .is_("referred_id", "null").limit(1).execute().data
    if existing:
        return {"referral_code": existing[0]["referral_code"], "existing": True}

    code = _generate_code(customer_name, customer_id)
    # Ensure uniqueness
    while sb.table("referrals").select("id").eq("referral_code", code).execute().data:
        code = _generate_code(customer_name, customer_id)

    result = sb.table("referrals").insert({
        "business_id": business_id,
        "referrer_id": customer_id,
        "referral_code": code,
        "reward_amount": reward_amount,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute().data
    return {"referral_code": code, "reward_amount": reward_amount, "created": True}


async def redeem_referral(business_id: str, referral_code: str, referred_customer_id: str) -> dict:
    """Mark a referral as converted when a referred customer books."""
    sb = get_supabase()
    referral = sb.table("referrals").select("*")\
        .eq("business_id", business_id).eq("referral_code", referral_code)\
        .eq("status", "active").limit(1).execute().data
    if not referral:
        return {"error": "Invalid or expired referral code"}
    r = referral[0]
    sb.table("referrals").update({
        "referred_id": referred_customer_id,
        "status": "converted",
        "converted_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", r["id"]).execute()
    # Queue reward for referrer
    from backend.dispatcher.dispatcher import dispatch
    from shared.schemas import TaskRequest, TaskPriority
    from uuid import UUID
    await dispatch(TaskRequest(
        business_id=UUID(business_id),
        created_by="referral_manager",
        workflow="send_loyalty_reward",
        priority=TaskPriority.NORMAL,
        parameters={"customer_id": r["referrer_id"], "reward_amount": r["reward_amount"],
                    "reason": f"Referral bonus — code {referral_code}"},
    ))
    return {"redeemed": True, "referrer_id": r["referrer_id"], "reward_amount": r["reward_amount"]}


async def get_referral_stats(business_id: str) -> dict:
    """Get referral program stats for the business."""
    sb = get_supabase()
    all_refs = sb.table("referrals").select("status,reward_amount")\
        .eq("business_id", business_id).execute().data or []
    total = len(all_refs)
    converted = [r for r in all_refs if r["status"] == "converted"]
    rewards_paid = sum(float(r.get("reward_amount") or 0) for r in converted)
    return {
        "total_referral_codes": total,
        "converted": len(converted),
        "conversion_rate": round(len(converted) / max(total, 1) * 100, 1),
        "total_rewards_paid": rewards_paid,
    }
