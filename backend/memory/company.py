from uuid import UUID
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


async def get_company_state(business_id: UUID) -> dict:
    sb = get_supabase()
    bid = str(business_id)
    today = datetime.now(timezone.utc).date().isoformat()

    appts = sb.table("appointments") \
        .select("id, status, revenue, scheduled_at") \
        .eq("business_id", bid) \
        .gte("scheduled_at", today) \
        .execute().data or []

    staff = sb.table("staff") \
        .select("id, name, role") \
        .eq("business_id", bid) \
        .eq("active", True) \
        .execute().data or []

    completed = [a for a in appts if a["status"] == "completed"]
    revenue_today = sum(a.get("revenue") or 0 for a in completed)

    return {
        "appointments_today": len(appts),
        "completed_today": len(completed),
        "no_shows_today": len([a for a in appts if a["status"] == "no_show"]),
        "revenue_today": revenue_today,
        "active_staff": len(staff),
    }
