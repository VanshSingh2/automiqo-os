"""10pm daily: runs learning loop for all active businesses."""
import os
import asyncio
from backend.memory.supabase_client import get_supabase
from agents.departments.learning.agent import LearningDirectorAgent
from uuid import UUID


async def run_nightly_learning():
    sb = get_supabase()
    businesses = sb.table("businesses").select("id").eq("active", True).execute().data or []
    for biz in businesses:
        try:
            bid = UUID(biz["id"])
            agent = LearningDirectorAgent(business_id=bid)
            response = await agent.run(
                "Analyze this week's failures, knowledge gaps, and call quality. Generate improvement recommendations."
            )
            for rec in response.recommendations:
                sb.table("recommendations").insert({
                    "business_id": str(bid),
                    "generated_by": "learning_director",
                    "category": "improvement",
                    "title": rec[:100],
                    "description": rec,
                    "priority": "normal",
                    "status": "pending",
                }).execute()
        except Exception as e:
            print(f"Nightly learning failed for {biz['id']}: {e}")


if __name__ == "__main__":
    asyncio.run(run_nightly_learning())
