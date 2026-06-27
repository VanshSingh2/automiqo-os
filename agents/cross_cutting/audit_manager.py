from uuid import UUID
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


async def log_audit_event(
    business_id: UUID,
    trigger_type: str,
    trigger_data: dict,
    agent_chain: list,
    workflow_executed: str,
    result: str,
    revenue_impact: float = 0,
    duration_ms: int = 0,
) -> dict:
    """Write audit trail entry."""
    sb = get_supabase()
    entry = {
        "business_id": str(business_id),
        "trigger_type": trigger_type,
        "trigger_data": trigger_data,
        "agent_chain": agent_chain,
        "workflow_executed": workflow_executed,
        "result": result,
        "revenue_impact": revenue_impact,
        "duration_ms": duration_ms,
    }
    result_row = sb.table("audit_log").insert(entry).execute()
    return result_row.data[0] if result_row.data else {}


async def get_recent_audit(business_id: UUID, limit: int = 20) -> list:
    sb = get_supabase()
    return sb.table("audit_log").select("*").eq("business_id", str(business_id)).order("created_at", desc=True).limit(limit).execute().data or []
