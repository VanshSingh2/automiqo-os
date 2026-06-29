"""
Business Intelligence Engine — nightly analysis, trend identification,
root cause analysis, recommendations, and action plans.
The most powerful engine — synthesizes everything into strategic intelligence.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from backend.memory.supabase_client import get_supabase


class BusinessIntelligenceEngine:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("CEO_MODEL", "gpt-4.1").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def run_nightly_analysis(self, business_id: str) -> dict:
        """
        Deep nightly analysis — runs after all dept loops complete.
        Synthesizes KPIs, patterns, failures, customer trends, and produces:
        - Key trends identified
        - Root causes of problems
        - Strategic recommendations
        - Priority action plan for tomorrow
        """
        import asyncio
        from backend.engines.kpi_engine import kpi_engine
        from backend.engines.goal_engine import goal_engine
        from backend.engines.opportunity_engine import opportunity_engine
        from backend.engines.prediction_engine import prediction_engine
        from backend.engines.knowledge_gap_detector import knowledge_gap_detector
        from backend.engines.cost_optimizer import cost_optimizer

        sb = get_supabase()
        bid = business_id
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()

        # Gather all intelligence
        kpis, off_track, opportunities, forecast, gaps, cost_report = await asyncio.gather(
            kpi_engine.snapshot(bid),
            goal_engine.get_off_track_goals(bid),
            opportunity_engine.scan(bid),
            prediction_engine.full_forecast(bid),
            knowledge_gap_detector.detect_from_failures(bid, since_hours=24),
            cost_optimizer.get_weekly_spend_report(bid),
        )

        # Get recent reflections and mistakes
        reflections = sb.table("reflections").select("what_happened,lesson,mistake")\
            .eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        mistakes = [r for r in reflections if r.get("mistake")]
        wins = [r for r in reflections if not r.get("mistake")]

        # Conversation funnel
        convs = sb.table("conversations").select("state").eq("business_id", bid)\
            .gte("created_at", week_ago).execute().data or []

        bi_context = {
            "date": now.strftime("%Y-%m-%d"),
            "kpis": kpis,
            "off_track_goals": [g.get("title") for g in off_track[:5]],
            "top_3_opportunities": [o.get("title") for o in opportunities[:3]],
            "revenue_forecast_7d": forecast.get("revenue_forecast", {}).get("total_predicted", 0),
            "churn_risk_customers": forecast.get("churn_forecast", {}).get("churn_risk_customers", 0),
            "knowledge_gaps": [g.get("workflow") + ": " + g.get("gap_type") for g in gaps[:5]],
            "ai_cost_7d": cost_report.get("total_cost_7d", 0),
            "mistakes_this_week": len(mistakes),
            "wins_this_week": len(wins),
            "conversation_funnel": {
                "total": len(convs),
                "booked": sum(1 for c in convs if c.get("state") == "booked"),
                "interested": sum(1 for c in convs if c.get("state") == "interested"),
            },
        }

        messages = [
            SystemMessage(content=(
                "You are the Business Intelligence Engine for an AI business OS. "
                "Perform deep analysis and generate strategic intelligence. "
                "Be specific about numbers, percentages, and business impact. "
                "Respond with valid JSON: "
                "{executive_summary: str, "
                "key_trends: [{trend, impact, confidence}], "
                "root_causes: [{problem, root_cause, evidence}], "
                "strategic_recommendations: [{recommendation, expected_impact, timeline, owner_dept}], "
                "tomorrow_action_plan: [{priority, action, workflow, expected_result}], "
                "health_score: 0-100}"
            )),
            HumanMessage(content=f"Intelligence data:\n{json.dumps(bi_context, default=str)[:4000]}"),
        ]

        try:
            resp = await self._get_llm().ainvoke(messages)
            import re
            raw = resp.content.strip()
            m = re.search(r"```[\w]*\s*([\s\S]*?)```", raw)
            analysis = json.loads(m.group(1).strip() if m else raw)
        except Exception as e:
            analysis = {
                "executive_summary": f"BI analysis error: {e}",
                "key_trends": [], "root_causes": [], "strategic_recommendations": [],
                "tomorrow_action_plan": [], "health_score": 50,
            }

        analysis["generated_at"] = now.isoformat()
        analysis["raw_data"] = bi_context

        # Save strategic recommendations
        for rec in analysis.get("strategic_recommendations", [])[:5]:
            try:
                sb.table("recommendations").insert({
                    "business_id": bid,
                    "generated_by": "business_intelligence",
                    "category": "strategic",
                    "title": rec.get("recommendation", "")[:100],
                    "description": f"Impact: {rec.get('expected_impact','')} | Timeline: {rec.get('timeline','')} | Owner: {rec.get('owner_dept','')}",
                    "priority": "high",
                    "status": "pending",
                }).execute()
            except Exception:
                pass

        # Save report
        try:
            sb.table("reports").insert({
                "business_id": bid,
                "report_date": now.date().isoformat(),
                "report_type": "nightly_bi_analysis",
                "content": analysis,
                "summary": analysis.get("executive_summary", "")[:500],
            }).execute()
        except Exception:
            pass

        return analysis


# Singleton
business_intelligence = BusinessIntelligenceEngine()
