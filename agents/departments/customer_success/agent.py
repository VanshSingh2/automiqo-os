import os
import json
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from agents.departments.customer_success.managers.reputation_manager import ReputationManager
from agents.departments.customer_success.managers.customer_success_manager import CustomerSuccessManager
from agents.departments.customer_success.managers.loyalty_manager import LoyaltyManager
from backend.memory.supabase_client import get_supabase


class CustomerSuccessAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        managers = [ReputationManager, CustomerSuccessManager, LoyaltyManager]
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
        open_complaints = sb.table("calls").select("id,sentiment").eq("business_id", bid).eq("sentiment", "negative").execute().data or []
        all_customers = sb.table("customers").select("id,tags").eq("business_id", bid).execute().data or []
        churn_risk = [c for c in all_customers if "churn_risk" in (c.get("tags") or [])]
        state = {"open_complaints": len(open_complaints), "churn_risk": len(churn_risk)}
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("customer_success_director")
        except Exception:
            prompt = "You are the Customer Success Director. Respond with JSON: {status, summary, metrics, recommendations}."
        # Consult specialists before LLM call
        _q = question.lower()
        _consultations = []
        if any(w in _q for w in ["complaint", "unhappy", "refund", "issue", "problem", "angry"]):
            _consultations.append({"specialist": "customer_service", "task": question})
        if any(w in _q for w in ["review", "reputation", "rating", "google", "feedback"]):
            _consultations.append({"specialist": "pr_communications_manager", "task": question})
        if any(w in _q for w in ["retain", "churn", "loyalty", "returning", "rebook"]):
            _consultations.append({"specialist": "customer_success_manager", "task": question})
        if any(w in _q for w in ["experience", "satisfaction", "survey", "nps", "feeling"]):
            _consultations.append({"specialist": "hospitality_guest_services", "task": question})
        if _consultations:
            _insights = await self.consult_specialists_parallel(_consultations)
            _specialist_block = "\n\n## Specialist Insights\n" + "\n".join(
                f"### {k.replace('_', ' ').title()}\n{v}" for k, v in _insights.items()
            )
        else:
            _specialist_block = ""
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}{_specialist_block}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
