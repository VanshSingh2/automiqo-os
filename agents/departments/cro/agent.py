import os
import json
import asyncio
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from agents.departments.cro.managers.revenue_recovery_manager import RevenueRecoveryManager
from agents.departments.cro.managers.pricing_manager import PricingManager
from agents.departments.cro.managers.membership_manager import MembershipManager
from agents.departments.cro.managers.upsell_manager import UpsellManager
from agents.departments.cro.managers.goal_manager import GoalManager
from backend.memory.customer import get_dormant_customers
from backend.memory.supabase_client import get_supabase


class CROAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        """Run all sub-managers in parallel and merge their summaries."""
        managers = [RevenueRecoveryManager, PricingManager, MembershipManager, UpsellManager, GoalManager]
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
        dormant = await get_dormant_customers(self.business_id, inactive_days=30)
        sb = get_supabase()
        all_customers = sb.table("customers").select("id,tags").eq("business_id", str(self.business_id)).execute().data or []
        at_risk = [c for c in all_customers if "churn_risk" in (c.get("tags") or [])]
        state = {"dormant_30d": len(dormant), "churn_risk_count": len(at_risk)}
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("cro")
        except Exception:
            prompt = "You are the CRO. Respond with JSON: {status, summary, metrics, recommendations}."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:

        # Strip markdown code fences
        _c = response.content.strip()
        if _c.startswith('```'):
            parts = _c.split('```')
            _c = parts[2].strip() if len(parts) >= 3 else parts[-1].strip()
            _c = _c.lstrip('json').strip()
                    parsed = json.loads(_c)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", response.content),
                metrics={**state, **parsed.get("metrics", {})},
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
