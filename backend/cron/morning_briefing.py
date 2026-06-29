"""7am daily: CEO standup — fires daily.standup event for all active businesses."""
import os
import asyncio
from backend.memory.supabase_client import get_supabase
from uuid import UUID


async def run_morning_briefing():
    sb = get_supabase()
    businesses = sb.table("businesses").select("id,name,timezone").eq("active", True).execute().data or []

    for biz in businesses:
        try:
            bid = str(biz["id"])
            # Fire daily standup event — CEO agent handles autonomously
            from backend.events.bus import publish, E
            await publish(bid, E.DAILY_STANDUP, {
                "business_name": biz.get("name", ""),
                "timezone": biz.get("timezone", "America/New_York"),
            }, source="morning_cron")

            # Also run hourly heartbeat checks
            from backend.events.worker import run_hourly_heartbeat
            await run_hourly_heartbeat(bid)

        except Exception as e:
            print(f"Morning briefing failed for {biz['id']}: {e}")


if __name__ == "__main__":
    asyncio.run(run_morning_briefing())
