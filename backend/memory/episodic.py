from datetime import datetime, timedelta, timezone
from uuid import UUID
from backend.memory.supabase_client import get_supabase


async def get_recent_events(business_id: UUID, days: int = 7) -> dict:
    sb = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    bid = str(business_id)

    appointments = sb.table("appointments") \
        .select("*") \
        .eq("business_id", bid) \
        .gte("created_at", since) \
        .execute().data or []

    calls = sb.table("calls") \
        .select("*") \
        .eq("business_id", bid) \
        .gte("called_at", since) \
        .execute().data or []

    return {"appointments": appointments, "calls": calls}
