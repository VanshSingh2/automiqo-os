"""
Strategy Planner — produces proactive daily executive plans with priorities, risks, and opportunities.
Runs at 7am CEO standup. Tells CEO exactly what to focus on today.
"""
import os
import json
from datetime import datetime, timezone
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


class StrategyPlanner:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("CEO_MODEL", "gpt-4.1").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def generate_daily_plan(self, business_id: str) -> dict:
        """
        Generate today's executive action plan.
        Integrates KPIs, goals, opportunities, predictions, and pending approvals.
        """
        from backend.engines.kpi_engine import kpi_engine
        from backend.engines.goal_engine import goal_engine
        from backend.engines.opportunity_engine import opportunity_engine
        from backend.engines.prediction_engine import prediction_engine

        # Gather all inputs in parallel
        import asyncio
        kpis, off_track_goals, opportunities, forecasts = await asyncio.gather(
            kpi_engine.snapshot(business_id),
            goal_engine.get_off_track_goals(business_id),
            opportunity_engine.scan(business_id),
            prediction_engine.full_forecast(business_id),
        )

        today = datetime.now(timezone.utc).strftime("%A, %B %d %Y")
        context = {
            "date": today,
            "kpis": kpis,
            "off_track_goals": off_track_goals[:5],
            "top_opportunities": opportunities[:3],
            "forecasts": forecasts,
        }

        messages = [
            SystemMessage(content=(
                "You are the Strategy Planner for an AI business operating system. "
                "Given the business data, generate a focused executive action plan for today. "
                "Be concrete — name specific workflows, metrics, and priorities. "
                "Respond with valid JSON: "
                "{today_priorities: [{rank, action, why, workflow, urgency}], "
                "risks_to_watch: [{risk, mitigation}], "
                "opportunities_to_capture: [{opportunity, potential_value, action}], "
                "key_metric_to_move: {metric, current, target, how}}"
            )),
            HumanMessage(content=f"Business data for {today}:\n{json.dumps(context, default=str)[:3000]}"),
        ]

        try:
            resp = await self._get_llm().ainvoke(messages)
            import re
            raw = resp.content.strip()
            m = re.search(r"```[\w]*\s*([\s\S]*?)```", raw)
            plan = json.loads(m.group(1).strip() if m else raw)
        except Exception as e:
            plan = {
                "today_priorities": [{"rank": 1, "action": "Review KPIs", "why": "Strategy planner error", "workflow": "generate_daily_report", "urgency": "normal"}],
                "risks_to_watch": [],
                "opportunities_to_capture": [],
                "key_metric_to_move": {},
                "error": str(e),
            }

        plan["generated_at"] = datetime.now(timezone.utc).isoformat()
        plan["business_id"] = business_id
        return plan


# Singleton
strategy_planner = StrategyPlanner()
