import os
import json
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from agents.departments.cmo.managers.campaign_manager import CampaignManager
from agents.departments.cmo.managers.content_manager import ContentManager
from agents.departments.cmo.managers.lead_manager import LeadManager
from agents.departments.cmo.managers.experiment_manager import ExperimentManager
from agents.departments.cmo.managers.customer_insights_manager import CustomerInsightsManager
from backend.memory.supabase_client import get_supabase


class CMOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        """Run all sub-managers in parallel and merge their summaries."""
        managers = [CampaignManager, ContentManager, LeadManager, ExperimentManager, CustomerInsightsManager]
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
        campaigns = sb.table("campaigns").select("id,name,status,sent_count,response_count,booking_count").eq("business_id", bid).limit(10).execute().data or []
        active = [c for c in campaigns if c["status"] == "running"]
        state = {
            "active_campaigns": len(active),
            "total_campaigns": len(campaigns),
            "total_sent": sum(c.get("sent_count") or 0 for c in campaigns),
            "total_bookings_from_campaigns": sum(c.get("booking_count") or 0 for c in campaigns),
        }
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("cmo")
        except Exception:
            prompt = "You are the CMO. Respond with JSON: {status, summary, metrics, recommendations}."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
