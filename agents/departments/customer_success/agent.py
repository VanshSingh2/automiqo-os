import os
import json
import asyncio
from uuid import UUID
from langchain_openai import ChatOpenAI
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
        """Run all sub-managers in parallel and merge their summaries."""
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
