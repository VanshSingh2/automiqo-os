from uuid import UUID
from typing import Optional
from datetime import datetime, timedelta, timezone
from backend.memory.supabase_client import get_supabase


async def get_customer_by_phone(business_id: UUID, phone: str) -> Optional[dict]:
    sb = get_supabase()
    result = sb.table("customers") \
        .select("*") \
        .eq("business_id", str(business_id)) \
        .eq("phone", phone) \
        .limit(1) \
        .execute()
    return result.data[0] if result.data else None


async def get_dormant_customers(business_id: UUID, inactive_days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
    sb = get_supabase()
    result = sb.table("customers") \
        .select("*") \
        .eq("business_id", str(business_id)) \
        .eq("opt_out_sms", False) \
        .lt("last_visit", cutoff) \
        .execute()
    return result.data or []
