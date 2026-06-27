import os
import json
from uuid import UUID
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


async def create_internal_task(
    business_id: UUID,
    title: str,
    description: str,
    assigned_by: str,
    department: str,
    priority: str = "normal",
    due_date: str | None = None,
) -> dict:
    """Create internal business task (not customer-facing)."""
    sb = get_supabase()
    data = {
        "business_id": str(business_id),
        "title": title,
        "description": description,
        "assigned_by": assigned_by,
        "department": department,
        "priority": priority,
        "status": "open",
    }
    if due_date:
        data["due_date"] = due_date
    result = sb.table("internal_tasks").insert(data).execute()
    return result.data[0] if result.data else {}


async def get_overdue_tasks(business_id: UUID) -> list:
    sb = get_supabase()
    today = datetime.now(timezone.utc).date().isoformat()
    return sb.table("internal_tasks").select("*").eq("business_id", str(business_id)).eq("status", "open").lt("due_date", today).execute().data or []
