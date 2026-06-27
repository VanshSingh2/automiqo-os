"""7am daily: fires morning briefing for all active businesses."""
import os
import asyncio
from backend.memory.supabase_client import get_supabase
from agents.executive.ceo.agent import CEOAgent
from uuid import UUID


async def run_morning_briefing():
    sb = get_supabase()
    businesses = sb.table("businesses").select("id, name, timezone").eq("active", True).execute().data or []
    for biz in businesses:
        try:
            bid = UUID(biz["id"])
            agent = CEOAgent(business_id=bid)
            response = await agent.run(
                "Generate the morning briefing for the owner. Include: revenue yesterday, appointments today, any alerts, top 3 recommendations."
            )
            sb.table("reports").insert({
                "business_id": str(bid),
                "report_type": "daily",
                "content": {"metrics": response.metrics, "recommendations": response.recommendations},
                "summary": response.summary,
            }).execute()
        except Exception as e:
            print(f"Morning briefing failed for {biz['id']}: {e}")


if __name__ == "__main__":
    asyncio.run(run_morning_briefing())
