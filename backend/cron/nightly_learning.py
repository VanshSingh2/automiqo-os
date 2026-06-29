"""10pm daily: runs learning loop for all active businesses."""
import os
import asyncio
from backend.memory.supabase_client import get_supabase
from agents.departments.learning.agent import LearningDirectorAgent
from uuid import UUID


async def run_nightly_learning():
    """10pm: BI Engine + Knowledge Gap Detector + AI Mentor + Learning Agent."""
    from backend.engines.business_intelligence import business_intelligence
    from backend.engines.knowledge_gap_detector import knowledge_gap_detector
    from backend.engines.ai_mentor import ai_mentor
    from datetime import datetime, timezone

    sb = get_supabase()
    businesses = sb.table("businesses").select("id").eq("active", True).execute().data or []
    for biz in businesses:
        try:
            bid = UUID(biz["id"])
            bid_str = str(bid)

            # 1. Business Intelligence Engine — deep nightly analysis
            bi = await business_intelligence.run_nightly_analysis(bid_str)
            print(f"[nightly][{bid_str[:8]}] BI health_score={bi.get('health_score','?')}")

            # 2. Knowledge gap detection
            gaps = await knowledge_gap_detector.auto_store_gaps(bid_str)
            print(f"[nightly][{bid_str[:8]}] gaps stored: {gaps}")

            # 3. AI Mentor coaching (Sundays only)
            if datetime.now(timezone.utc).weekday() == 6:
                await ai_mentor.coach_all_departments(bid_str)
                print(f"[nightly][{bid_str[:8]}] AI Mentor coached depts")

            # 4. Learning Director reflection
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
