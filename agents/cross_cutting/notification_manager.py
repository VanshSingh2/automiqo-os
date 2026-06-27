import os
import json
from uuid import UUID
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


async def send_notification(
    business_id: UUID,
    recipient_type: str,
    recipient_id: str,
    channel: str,
    message: str,
) -> dict:
    """Log outbound notification. Actual send dispatched via n8n."""
    sb = get_supabase()
    result = sb.table("notifications_log").insert({
        "business_id": str(business_id),
        "recipient_type": recipient_type,
        "recipient_id": recipient_id,
        "channel": channel,
        "message": message,
        "status": "queued",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return result.data[0] if result.data else {}


async def get_notification_stats(business_id: UUID) -> dict:
    sb = get_supabase()
    logs = sb.table("notifications_log").select("channel, status").eq("business_id", str(business_id)).execute().data or []
    return {
        "total": len(logs),
        "by_channel": {ch: len([l for l in logs if l.get("channel") == ch]) for ch in ["sms", "email", "whatsapp"]},
        "failed": len([l for l in logs if l.get("status") == "failed"]),
    }
