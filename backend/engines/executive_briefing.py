"""
Executive Briefing Generator — generates daily executive summaries covering every department.
Runs at 7am and replaces the old morning_briefing.py logic with a richer, structured format.
"""
import os
import json
from datetime import datetime, timezone
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from backend.memory.supabase_client import get_supabase


class ExecutiveBriefingGenerator:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("CEO_MODEL", "gpt-4.1").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def generate(self, business_id: str) -> dict:
        """
        Full executive briefing — pulls from all engines and depts.
        Saved to reports table. Sent to owner via CEO chat on request.
        """
        import asyncio
        from backend.engines.kpi_engine import kpi_engine
        from backend.engines.goal_engine import goal_engine
        from backend.engines.opportunity_engine import opportunity_engine
        from backend.engines.prediction_engine import prediction_engine
        from backend.engines.strategy_planner import strategy_planner
        from backend.engines.risk_manager import risk_manager

        sb = get_supabase()
        biz = sb.table("businesses").select("name,industry").eq("id", business_id).limit(1).execute()
        biz_data = biz.data[0] if biz.data else {}

        # Gather all data
        kpis, opportunities, forecast, plan, off_track = await asyncio.gather(
            kpi_engine.snapshot(business_id),
            opportunity_engine.scan(business_id),
            prediction_engine.full_forecast(business_id),
            strategy_planner.generate_daily_plan(business_id),
            goal_engine.get_off_track_goals(business_id),
        )

        # Pending approvals
        pending = sb.table("recommendations").select("title,priority").eq("business_id", business_id)\
            .eq("status", "pending").execute().data or []

        today = datetime.now(timezone.utc).strftime("%A, %B %d %Y")

        briefing_context = {
            "business": biz_data,
            "date": today,
            "kpis": kpis,
            "top_opportunities": opportunities[:3],
            "revenue_forecast_7d": forecast.get("revenue_forecast", {}).get("total_predicted", 0),
            "churn_risk_count": forecast.get("churn_forecast", {}).get("churn_risk_customers", 0),
            "off_track_goals": [g.get("title") for g in off_track[:3]],
            "today_priorities": plan.get("today_priorities", [])[:3],
            "pending_approvals": len(pending),
            "pending_titles": [p.get("title") for p in pending[:3]],
        }

        messages = [
            SystemMessage(content=(
                "You are generating the daily executive briefing for a local service business owner. "
                "Be concise, specific, and action-oriented. Cover: performance, alerts, opportunities, today's plan. "
                "Respond in JSON: {headline, performance_summary, alerts: [], opportunities: [], "
                "todays_plan: [], pending_approvals_count: int, closing_note}"
            )),
            HumanMessage(content=f"Data for {today}:\n{json.dumps(briefing_context, default=str)[:3000]}"),
        ]

        try:
            resp = await self._get_llm().ainvoke(messages)
            import re
            raw = resp.content.strip()
            m = re.search(r"```[\w]*\s*([\s\S]*?)```", raw)
            briefing = json.loads(m.group(1).strip() if m else raw)
        except Exception as e:
            briefing = {
                "headline": f"Daily Briefing — {today}",
                "performance_summary": f"KPIs loaded. Revenue today: ${kpis.get('revenue',{}).get('today',0):.0f}",
                "alerts": [],
                "opportunities": [o.get("title") for o in opportunities[:3]],
                "todays_plan": [p.get("action") for p in plan.get("today_priorities", [])[:3]],
                "pending_approvals_count": len(pending),
                "closing_note": "Have a great day!",
                "error": str(e),
            }

        briefing["generated_at"] = datetime.now(timezone.utc).isoformat()
        briefing["full_data"] = briefing_context

        # Save to reports table
        try:
            sb.table("reports").insert({
                "business_id": business_id,
                "report_date": datetime.now(timezone.utc).date().isoformat(),
                "report_type": "executive_briefing",
                "content": briefing,
                "summary": briefing.get("headline", "Daily briefing"),
            }).execute()
        except Exception:
            pass

        return briefing


# Singleton
executive_briefing = ExecutiveBriefingGenerator()
