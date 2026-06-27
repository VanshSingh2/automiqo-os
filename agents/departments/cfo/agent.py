import os
import json
import asyncio
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from agents.departments.cfo.managers.analytics_manager import AnalyticsManager
from agents.departments.cfo.managers.business_planner import BusinessPlanner
from agents.departments.cfo.managers.risk_manager import RiskManager
from backend.memory.supabase_client import get_supabase
from datetime import datetime, timezone, timedelta


class CFOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        """Run all sub-managers in parallel and merge their summaries."""
        managers = [AnalyticsManager, BusinessPlanner, RiskManager]
        tasks = [m(self.business_id).run(question, state) for m in managers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged = {}
        summaries = []
        for r in results:
            if isinstance(r, AgentResponse):
                summaries.append(r.summary)
                merged.update(r.metrics or {})
        merged["manager_insights"] = " | ".join(s for s in summaries if s)
        return merged

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()
        appts_week = sb.table("appointments").select("revenue,status").eq("business_id", bid).gte("scheduled_at", week_ago).execute().data or []
        appts_month = sb.table("appointments").select("revenue,status").eq("business_id", bid).gte("scheduled_at", month_ago).execute().data or []
        state = {
            "revenue_7d": sum(a.get("revenue") or 0 for a in appts_week if a["status"] == "completed"),
            "revenue_30d": sum(a.get("revenue") or 0 for a in appts_month if a["status"] == "completed"),
            "appts_week": len(appts_week),
            "no_shows_week": len([a for a in appts_week if a["status"] == "no_show"]),
        }
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("cfo")
        except Exception:
            prompt = "You are the CFO. Respond with JSON: {status, summary, metrics, recommendations}."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", response.content),
                metrics={**state, **parsed.get("metrics", {})},
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
